package com.worn.glasses;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.media.AudioManager;
import android.media.MediaActionSound;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.speech.tts.TextToSpeech;
import android.util.Log;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.WindowManager;
import android.webkit.ConsoleMessage;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.TextView;

import org.json.JSONObject;

import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Worn on the M6 glasses (agent B).
 *
 * The display is agent C's page (GET /glasses) in a full-screen WebView. This activity adds what a
 * web page can't do on the glasses: the touchpad/button, the camera, the upload to POST /grade, and
 * text-to-speech. Contract with web/glasses.html:
 *   - window.WornNative.speak(text)   page -> native, spoken with Android TTS
 *   - worn.capturing()                native -> page, shows "Checking..."
 *   - worn.graded(json)               native -> page, shows the check / fix and speaks it
 *   - worn.error(msg)                 native -> page
 *   - worn.replay()                   native -> page, re-runs the stroke animation + audio
 *
 * Keys (M6 Android SDK guide, section 12.8): tap = ENTER, double tap = F12, long press = F10,
 * swipe = DPAD_LEFT/RIGHT, photo button = CAMERA. Every key is logged under tag WornKeys.
 */
public class MainActivity extends Activity {
    private static final String TAG = "Worn";
    private static final String KEYS = "WornKeys";
    private static final String PREFS = "worn";

    private final Handler ui = new Handler(Looper.getMainLooper());
    private final ExecutorService net = Executors.newSingleThreadExecutor();
    /** Heartbeat + backend choice, separate from `net` so a slow /grade never delays it. */
    private final ExecutorService beat = Executors.newSingleThreadExecutor();
    private static final String USB_FALLBACK = "http://127.0.0.1:8000"; // adb reverse tcp:8000 tcp:8000
    private static final long BEAT_MS = 5000;

    private WebView web;
    private TextView status;
    private GlassesCamera camera;
    private TextToSpeech tts;
    private boolean ttsReady;
    private MediaActionSound shutter;
    private volatile String api;      // the backend in use right now
    private volatile String primary;  // Wi-Fi backend (intent extra `api`, remembered)
    private volatile String fallback; // used only while the primary can't be reached (USB / adb reverse)
    private boolean busy;
    private boolean pageLoaded;
    private String lastKey = "none";
    private final Runnable retryLoad = this::chooseAndLoad;
    private final Runnable heartbeat = new Runnable() {
        @Override public void run() {
            beat.execute(MainActivity.this::beatOnce);
            ui.postDelayed(this, BEAT_MS);
        }
    };
    private final Runnable hideStatus = () -> status.setVisibility(View.GONE);

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        setVolumeControlStream(AudioManager.STREAM_MUSIC);

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.BLACK); // black = see-through on the waveguide
        web = new WebView(this);
        web.setBackgroundColor(Color.BLACK);
        root.addView(web, new FrameLayout.LayoutParams(-1, -1));
        status = new TextView(this);
        status.setTextColor(0xFFFFC23D);
        status.setTextSize(20);
        status.setBackgroundColor(0xE0000000);
        status.setPadding(24, 16, 24, 16);
        status.setGravity(Gravity.CENTER);
        status.setVisibility(View.GONE);
        root.addView(status, new FrameLayout.LayoutParams(-1, -2, Gravity.BOTTOM));
        setContentView(root);
        hideSystemUi();

        setupWebView();
        tts = new TextToSpeech(this, st -> {
            ttsReady = st == TextToSpeech.SUCCESS;
            if (ttsReady) tts.setLanguage(Locale.US);
            Log.i(TAG, "tts ready=" + ttsReady);
        });
        shutter = new MediaActionSound();
        shutter.load(MediaActionSound.SHUTTER_CLICK);
        camera = new GlassesCamera(this);

        applyIntent(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        applyIntent(intent);
    }

    /** `am start ... --es api http://10.0.0.5:8000` switches the backend; the choice is remembered. */
    private void applyIntent(Intent intent) {
        SharedPreferences p = getSharedPreferences(PREFS, MODE_PRIVATE);
        String fromIntent = intent == null ? null : intent.getStringExtra("api");
        if (fromIntent != null && !fromIntent.trim().isEmpty()) {
            p.edit().putString("api", fromIntent.trim()).apply();
        }
        String fb = intent == null ? null : intent.getStringExtra("fallback");
        if (fb != null) p.edit().putString("fallback", fb.trim()).apply();
        primary = p.getString("api", BuildConfig.DEFAULT_API).replaceAll("/+$", "");
        fallback = p.getString("fallback", USB_FALLBACK).replaceAll("/+$", "");
        Log.i(TAG, "backend " + primary + " (fallback " + fallback + ")");
        chooseAndLoad();
    }

    /** Wi-Fi backend when it answers, else the USB fallback, else keep trying the Wi-Fi one. */
    private String pickApi() {
        String a = primary, b = fallback;
        if (new Backend(a).reachable()) return a;
        if (b != null && !b.isEmpty() && !b.equals(a) && new Backend(b).reachable()) return b;
        return a;
    }

    private void chooseAndLoad() {
        ui.removeCallbacks(retryLoad);
        beat.execute(() -> {
            String pick = pickApi();
            ui.post(() -> {
                boolean changed = !pick.equals(api);
                api = pick;
                Log.i(TAG, "using backend " + api + (pick.equals(primary) ? " (wifi)" : " (fallback)"));
                if (changed || !pageLoaded) loadPage();
            });
        });
    }

    /** Runs on `beat`: tells the backend the glasses are on (GET /health shows glasses.connected), and
     *  moves to the other backend if the current one stops answering or the Wi-Fi one comes back. */
    private void beatOnce() {
        String pick = pickApi();
        try {
            JSONObject d = new JSONObject().put("connected", true)
                    .put("via", pick.equals(primary) ? "wifi" : "usb").put("backend", pick);
            new Backend(pick).event("glasses", d);
        } catch (Exception e) {
            Log.w(TAG, "heartbeat to " + pick + " failed: " + e.getMessage());
        }
        if (!pick.equals(api)) ui.post(() -> {
            Log.i(TAG, "switching backend " + api + " -> " + pick);
            api = pick;
            loadPage();
        });
    }

    private void sayGoodbye() {
        String a = api;
        if (a == null) return;
        beat.execute(() -> {
            try { new Backend(a).event("glasses_disconnected", null); } catch (Exception ignored) { }
        });
    }

    @Override
    protected void onResume() {
        super.onResume();
        hideSystemUi();
        web.onResume();
        if (hasCamera()) camera.open();
        else flash("No camera permission. Reinstall with: adb install -r -g", 8000);
    }

    @Override
    protected void onStart() {
        super.onStart();
        ui.removeCallbacks(heartbeat);
        ui.post(heartbeat);
    }

    @Override
    protected void onStop() {
        ui.removeCallbacks(heartbeat);
        sayGoodbye();
        super.onStop();
    }

    @Override
    protected void onPause() {
        camera.close(); // let the built-in camera app have it when we're not in front
        web.onPause();
        super.onPause();
    }

    @Override
    protected void onDestroy() {
        ui.removeCallbacksAndMessages(null);
        camera.release();
        net.shutdownNow();
        beat.shutdown();
        if (tts != null) tts.shutdown();
        if (shutter != null) shutter.release();
        web.destroy();
        super.onDestroy();
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) hideSystemUi();
    }

    // ------------------------------------------------------------------ keys

    @Override
    public boolean dispatchKeyEvent(KeyEvent e) {
        int code = e.getKeyCode();
        if (e.getAction() == KeyEvent.ACTION_DOWN) {
            Log.i(KEYS, "down " + KeyEvent.keyCodeToString(code) + " (" + code + ") repeat=" + e.getRepeatCount()
                    + " source=0x" + Integer.toHexString(e.getSource()));
        }
        Action a = actionFor(code);
        if (a == Action.NONE) return super.dispatchKeyEvent(e); // back, home, volume, power behave normally
        // Act on key-up so a held key doesn't fire twice; swallow the down so the WebView doesn't scroll or click.
        if (e.getAction() == KeyEvent.ACTION_UP && !e.isCanceled()) {
            lastKey = KeyEvent.keyCodeToString(code);
            switch (a) {
                case CAPTURE: capture(); break;
                case REPLAY: js("worn.replay()"); break;
                case STATUS: showStatus(); break;
                default: break;
            }
        }
        return true;
    }

    private enum Action { NONE, CAPTURE, REPLAY, STATUS }

    private static Action actionFor(int code) {
        switch (code) {
            case KeyEvent.KEYCODE_ENTER:        // touchpad tap
            case KeyEvent.KEYCODE_DPAD_CENTER:
            case KeyEvent.KEYCODE_NUMPAD_ENTER:
            case KeyEvent.KEYCODE_CAMERA:       // photo button (if the system doesn't keep it for its camera app)
            case KeyEvent.KEYCODE_SPACE:        // `adb shell input keyevent 62` while testing
                return Action.CAPTURE;
            case KeyEvent.KEYCODE_F12:          // double tap
            case KeyEvent.KEYCODE_DPAD_LEFT:    // swipe left / right
            case KeyEvent.KEYCODE_DPAD_RIGHT:
                return Action.REPLAY;
            case KeyEvent.KEYCODE_F10:          // long press
                return Action.STATUS;
            default:
                return Action.NONE;
        }
    }

    // ------------------------------------------------------------------ photo -> grade

    private void capture() {
        if (busy) { Log.i(TAG, "capture ignored, still busy"); return; }
        if (!hasCamera()) { js("worn.error(" + JSONObject.quote("No camera permission") + ")"); return; }
        busy = true;
        js("worn.capturing()");
        camera.takePicture(new GlassesCamera.Callback() {
            @Override public void onJpeg(byte[] jpeg) {
                ui.post(() -> shutter.play(MediaActionSound.SHUTTER_CLICK));
                net.execute(() -> grade(jpeg));
            }
            @Override public void onError(String message) {
                Log.w(TAG, "camera: " + message);
                ui.post(() -> { busy = false; js("worn.error(" + JSONObject.quote(message) + ")"); });
            }
        });
    }

    /** Runs on the network thread. */
    private void grade(byte[] jpeg) {
        Backend b = new Backend(api);
        String ch = null, lang = null;
        try {
            JSONObject s = b.session();
            if (s != null) {
                ch = str(s, "char");
                lang = str(s, "lang");
                if ("asl".equals(s.optString("mode"))) { done("worn.error(" + JSONObject.quote("ASL mode: nothing to grade") + ")"); return; }
            }
        } catch (Exception e) {
            Log.w(TAG, "GET /session failed, letting the backend use its session", e);
        }
        try {
            long t0 = System.currentTimeMillis();
            String json = b.grade(jpeg, ch, lang);
            Log.i(TAG, "graded in " + (System.currentTimeMillis() - t0) + "ms: " + json);
            new JSONObject(json); // make sure it parses before handing it to the page
            done("worn.graded(" + JSONObject.quote(json) + ")");
        } catch (Backend.HttpError e) {
            Log.e(TAG, "grade http error", e);
            String msg = e.code == 503 ? "Grader is down, try again" :
                         e.code == 400 ? "Pick a phrase on your phone first" : "Server error " + e.code;
            done("worn.error(" + JSONObject.quote(msg) + ")");
        } catch (Exception e) {
            Log.e(TAG, "grade failed", e);
            done("worn.error(" + JSONObject.quote("Can't reach the server, press again") + ")");
        }
    }

    private void done(String script) {
        ui.post(() -> { busy = false; js(script); });
    }

    // ------------------------------------------------------------------ web view

    private void setupWebView() {
        WebSettings ws = web.getSettings();
        ws.setJavaScriptEnabled(true);
        ws.setDomStorageEnabled(true);
        ws.setMediaPlaybackRequiresUserGesture(false); // pronunciation audio + ASL video autoplay
        ws.setCacheMode(WebSettings.LOAD_NO_CACHE);
        ws.setUseWideViewPort(true);
        ws.setLoadWithOverviewMode(true);
        web.setVerticalScrollBarEnabled(false);
        web.setHorizontalScrollBarEnabled(false);
        web.setFocusable(false); // keys come to the activity, not the page
        web.addJavascriptInterface(new Bridge(), "WornNative");
        web.setWebChromeClient(new WebChromeClient() {
            @Override public boolean onConsoleMessage(ConsoleMessage m) {
                Log.i("WornWeb", m.message() + " @" + m.sourceId() + ":" + m.lineNumber());
                return true;
            }
        });
        web.setWebViewClient(new WebViewClient() {
            @Override public void onPageFinished(WebView v, String url) {
                Log.i(TAG, "page loaded " + url);
            }
            @Override public void onReceivedError(WebView v, WebResourceRequest req, WebResourceError err) {
                if (!req.isForMainFrame()) return;
                pageLoaded = false;
                Log.w(TAG, "page error " + err.getErrorCode() + " " + err.getDescription());
                showOffline();
            }
            @Override public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest req) {
                return false;
            }
        });
    }

    private void loadPage() {
        ui.removeCallbacks(retryLoad);
        pageLoaded = true; // cleared by onReceivedError
        String url = api + "/glasses?api=" + Uri.encode(api);
        Log.i(TAG, "loading " + url);
        web.loadUrl(url);
    }

    private void showOffline() {
        web.loadDataWithBaseURL(null,
                "<html><body style='background:#000;color:#8a8f98;font:26px sans-serif;text-align:center'>"
                        + "<h1 style='color:#fff;font-size:60px;margin-top:130px;letter-spacing:4px'>WORN</h1>"
                        + "<p>Looking for the server…</p><p style='font-size:18px'>" + escape(api) + "</p></body></html>",
                "text/html", "utf-8", null);
        ui.removeCallbacks(retryLoad);
        ui.postDelayed(retryLoad, 3000);
    }

    private void js(String script) {
        Log.d(TAG, "js " + (script.length() > 160 ? script.substring(0, 160) + "…" : script));
        web.evaluateJavascript("window.worn && " + script, null);
    }

    private final class Bridge {
        @JavascriptInterface
        public void speak(String text) {
            if (text == null || text.isEmpty()) return;
            if (!ttsReady) { Log.w(TAG, "tts not ready: " + text); return; }
            tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, "worn");
        }
    }

    // ------------------------------------------------------------------ misc

    private void showStatus() {
        flash("server " + api + "\n" + camera.describe() + "  ·  tts " + (ttsReady ? "on" : "off")
                + "  ·  last key " + lastKey, 5000);
    }

    private void flash(String text, long ms) {
        status.setText(text);
        status.setVisibility(View.VISIBLE);
        ui.removeCallbacks(hideStatus);
        ui.postDelayed(hideStatus, ms);
    }

    private boolean hasCamera() {
        return checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED;
    }

    private void hideSystemUi() {
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_FULLSCREEN
                | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                | View.SYSTEM_UI_FLAG_LAYOUT_STABLE);
    }

    /** optString() turns a JSON null into the string "null"; this returns a real null. */
    private static String str(JSONObject o, String key) {
        if (o.isNull(key)) return null;
        String v = o.optString(key, "");
        return v.isEmpty() ? null : v;
    }

    private static String escape(String s) {
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;");
    }
}
