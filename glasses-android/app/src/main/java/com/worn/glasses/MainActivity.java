package com.worn.glasses;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.media.AudioAttributes;
import android.media.AudioManager;
import android.media.MediaActionSound;
import android.media.MediaPlayer;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.view.KeyEvent;
import android.view.View;
import android.view.WindowManager;
import android.webkit.ConsoleMessage;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.util.ArrayDeque;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Worn on the M6 glasses: a voice-first app (agent D).
 *
 * The screens are our own page, assets/ui/index.html, loaded with the backend as its base URL so it can
 * call the backend directly and use B's shared scripts (/static/web/worn-ink.js …). This activity adds
 * what a page can't do on the glasses:
 *   - the microphone: always listening, cut into utterances, POST /voice  -> worn.voice(json)
 *   - the speaker: /say lines and pronunciation clips, one at a time (the mic is muted meanwhile)
 *   - the camera: Native.capture() -> POST /grade -> worn.graded(json)
 *   - the button / touchpad -> worn.key(name)   (backup only; voice drives everything)
 *   - which backend to use (Wi-Fi first, USB/adb reverse as fallback) and the connected heartbeat
 *
 * Test without speaking: adb shell am start -n com.worn.glasses/.MainActivity --es say "learn greek"
 */
public class MainActivity extends Activity {
    private static final String TAG = "Worn";
    private static final String KEYS = "WornKeys";
    private static final String PREFS = "worn";
    private static final String USB_FALLBACK = "http://127.0.0.1:8000"; // adb reverse tcp:8000 tcp:8000
    private static final long BEAT_MS = 5000;

    private final Handler ui = new Handler(Looper.getMainLooper());
    private final ExecutorService net = Executors.newSingleThreadExecutor();   // /grade
    private final ExecutorService talk = Executors.newSingleThreadExecutor();  // /voice
    private final ExecutorService beat = Executors.newSingleThreadExecutor();  // heartbeat, backend choice

    private WebView web;
    private GlassesCamera camera;
    private MediaActionSound shutter;
    private VoiceListener mic;
    private InkWatcher inkWatch;
    private volatile String api;      // the backend in use right now
    private volatile String primary;  // Wi-Fi backend (intent extra `api`, remembered)
    private volatile String fallback; // used only while the primary can't be reached (USB / adb reverse)
    private volatile String screen = "home";
    private volatile boolean wantMic = true;
    private boolean busy;
    private boolean pageReady;
    private String pendingSay;

    private final Runnable retryLoad = this::chooseAndLoad;
    private final Runnable heartbeat = new Runnable() {
        @Override public void run() {
            beat.execute(MainActivity.this::beatOnce);
            ui.postDelayed(this, BEAT_MS);
        }
    };

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
        setContentView(root);
        hideSystemUi();
        setupWebView();
        shutter = new MediaActionSound();
        shutter.load(MediaActionSound.SHUTTER_CLICK);
        camera = new GlassesCamera(this);
        inkWatch = new InkWatcher((frac, ms) -> {
            Log.i(TAG, "new ink " + frac + " (" + ms + " ms)");
            js("worn.ink(" + frac + "," + ms + ")");
        });
        camera.setLumaListener(inkWatch::onFrame);
        mic = new VoiceListener(new VoiceListener.Callback() {
            @Override public void onState(String s) { js("worn.mic(" + JSONObject.quote(s) + ")"); }
            @Override public void onUtterance(byte[] wav, int ms) { sendVoice(wav, ms); }
            @Override public void onLevel(float rms, float floor) {
                Log.v("WornVoice", "rms " + (int) rms + " floor " + (int) floor);
            }
        });
        applyIntent(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        applyIntent(intent);
    }

    /**
     * Extras: `api` (Wi-Fi backend, remembered), `fallback`, `say` (pretend the wearer said this),
     * `key` (pretend a button: tap|double|long|left|right).
     */
    private void applyIntent(Intent intent) {
        SharedPreferences p = getSharedPreferences(PREFS, MODE_PRIVATE);
        String fromIntent = intent == null ? null : intent.getStringExtra("api");
        if (fromIntent != null && !fromIntent.trim().isEmpty()) p.edit().putString("api", fromIntent.trim()).apply();
        String fb = intent == null ? null : intent.getStringExtra("fallback");
        if (fb != null) p.edit().putString("fallback", fb.trim()).apply();
        String nextPrimary = p.getString("api", BuildConfig.DEFAULT_API).replaceAll("/+$", "");
        String nextFallback = p.getString("fallback", USB_FALLBACK).replaceAll("/+$", "");
        boolean changed = !nextPrimary.equals(primary) || !nextFallback.equals(fallback);
        primary = nextPrimary;
        fallback = nextFallback;
        if (changed || !pageReady) {
            Log.i(TAG, "backend " + primary + " (fallback " + fallback + ")");
            chooseAndLoad();
        }
        if (intent != null && intent.hasExtra("loud")) p.edit().putInt("loud", intent.getIntExtra("loud", 1800)).apply();
        mic.minLoud = p.getInt("loud", 1800);
        String say = intent == null ? null : intent.getStringExtra("say");
        if (say != null && !say.isEmpty()) {
            if (pageReady) js("worn.heard(" + JSONObject.quote(say) + ")"); else pendingSay = say;
        }
        String key = intent == null ? null : intent.getStringExtra("key");
        if (key != null && pageReady) js("worn.key(" + JSONObject.quote(key) + ")");
        if (intent != null) { intent.removeExtra("say"); intent.removeExtra("key"); }
    }

    // ------------------------------------------------------------------ backend choice + heartbeat

    /** Wi-Fi backend when it answers, else the USB fallback; null when neither answers. */
    private String pickApi() {
        String a = primary, b = fallback;
        if (new Backend(a).reachable()) return a;
        if (b != null && !b.isEmpty() && !b.equals(a) && new Backend(b).reachable()) return b;
        return null;
    }

    private void chooseAndLoad() {
        ui.removeCallbacks(retryLoad);
        beat.execute(() -> {
            String pick = pickApi();
            ui.post(() -> {
                if (pick == null) { showOffline(); return; }
                Log.i(TAG, "using backend " + pick + (pick.equals(primary) ? " (wifi)" : " (fallback)"));
                api = pick;
                loadPage();
            });
        });
    }

    private void beatOnce() {
        String pick = pickApi();
        if (pick == null) {
            if (pageReady) ui.post(() -> { if (pageReady) { pageReady = false; showOffline(); } });
            return;
        }
        try {
            JSONObject d = new JSONObject().put("connected", true)
                    .put("via", pick.equals(primary) ? "wifi" : "usb").put("backend", pick);
            new Backend(pick).event("glasses", d);
        } catch (Exception e) {
            Log.w(TAG, "heartbeat to " + pick + " failed: " + e.getMessage());
        }
        if (!pick.equals(api) || !pageReady) ui.post(() -> {
            Log.i(TAG, "switching backend " + api + " -> " + pick);
            api = pick;
            loadPage();
        });
    }

    // ------------------------------------------------------------------ lifecycle

    @Override
    protected void onStart() {
        super.onStart();
        ui.removeCallbacks(heartbeat);
        ui.post(heartbeat);
    }

    @Override
    protected void onResume() {
        super.onResume();
        hideSystemUi();
        web.onResume();
        if (has(Manifest.permission.CAMERA)) camera.open();
        if (wantMic) startMic();
    }

    @Override
    protected void onPause() {
        mic.stop();
        camera.close(); // let the built-in camera app have it when we're not in front
        web.onPause();
        super.onPause();
    }

    @Override
    protected void onStop() {
        ui.removeCallbacks(heartbeat);
        String a = api;
        if (a != null) beat.execute(() -> {
            try { new Backend(a).event("glasses_disconnected", null); } catch (Exception ignored) { }
        });
        super.onStop();
    }

    @Override
    protected void onDestroy() {
        ui.removeCallbacksAndMessages(null);
        mic.stop();
        stopAudio();
        camera.release();
        net.shutdownNow();
        talk.shutdownNow();
        beat.shutdown();
        if (shutter != null) shutter.release();
        web.destroy();
        super.onDestroy();
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) hideSystemUi();
    }

    // ------------------------------------------------------------------ voice

    private void startMic() {
        if (!has(Manifest.permission.RECORD_AUDIO)) { Log.w(TAG, "no RECORD_AUDIO (install with adb install -g)"); return; }
        mic.start();
    }

    private void sendVoice(byte[] wav, int ms) {
        final String a = api, s = screen;
        if (a == null) return;
        js("worn.mic('thinking')");
        talk.execute(() -> {
            long t0 = System.currentTimeMillis();
            try {
                String json = new Backend(a).voice(wav, s);
                Log.i(TAG, "voice " + ms + "ms audio -> " + (System.currentTimeMillis() - t0) + "ms: " + json);
                js("worn.voice(" + JSONObject.quote(json) + ")");
            } catch (Backend.HttpError e) {
                Log.w(TAG, "voice http " + e.code);
                js("worn.voiceError(" + e.code + ")");
            } catch (Exception e) {
                Log.w(TAG, "voice failed: " + e.getMessage());
                js("worn.voiceError(0)");
            }
        });
    }

    // ------------------------------------------------------------------ speaker

    private final ArrayDeque<String> audioQueue = new ArrayDeque<>();
    private MediaPlayer player;

    private void playUrl(String url) {
        audioQueue.add(url);
        if (player == null) playNext();
    }

    private void playNext() {
        String url = audioQueue.poll();
        if (url == null) {
            mic.resume(350);
            js("worn.audioDone()");
            return;
        }
        mic.pause();
        MediaPlayer mp = new MediaPlayer();
        player = mp;
        try {
            mp.setAudioAttributes(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build());
            mp.setDataSource(url);
            mp.setOnPreparedListener(MediaPlayer::start);
            mp.setOnCompletionListener(m -> finishPlayer(m));
            mp.setOnErrorListener((m, what, extra) -> { Log.w(TAG, "audio error " + what + " " + url); finishPlayer(m); return true; });
            mp.prepareAsync();
            ui.postDelayed(() -> { if (player == mp && !mp.isPlaying()) { Log.w(TAG, "audio stuck, skipping " + url); finishPlayer(mp); } }, 8000);
        } catch (Exception e) {
            Log.w(TAG, "audio failed " + url, e);
            finishPlayer(mp);
        }
    }

    private void finishPlayer(MediaPlayer m) {
        try { m.release(); } catch (Exception ignored) { }
        if (player == m) player = null;
        ui.post(() -> { if (player == null) playNext(); });
    }

    private void stopAudio() {
        audioQueue.clear();
        MediaPlayer m = player;
        player = null;
        if (m != null) { try { m.stop(); } catch (Exception ignored) { } try { m.release(); } catch (Exception ignored) { } }
        mic.resume(250);
    }

    private String abs(String u) {
        if (u == null) return null;
        if (u.startsWith("http://") || u.startsWith("https://")) return u;
        return api + (u.startsWith("/") ? u : "/" + u);
    }

    // ------------------------------------------------------------------ keys (backup)

    @Override
    public boolean dispatchKeyEvent(KeyEvent e) {
        int code = e.getKeyCode();
        if (e.getAction() == KeyEvent.ACTION_DOWN) {
            Log.i(KEYS, "down " + KeyEvent.keyCodeToString(code) + " (" + code + ") repeat=" + e.getRepeatCount());
        }
        String name = keyName(code);
        if (name == null) return super.dispatchKeyEvent(e); // back, home, volume, power behave normally
        if (e.getAction() == KeyEvent.ACTION_UP && !e.isCanceled()) js("worn.key(" + JSONObject.quote(name) + ")");
        return true;
    }

    private static String keyName(int code) {
        switch (code) {
            case KeyEvent.KEYCODE_ENTER: case KeyEvent.KEYCODE_DPAD_CENTER: case KeyEvent.KEYCODE_NUMPAD_ENTER:
            case KeyEvent.KEYCODE_CAMERA: case KeyEvent.KEYCODE_SPACE:
                return "tap";
            case KeyEvent.KEYCODE_F12: return "double";
            case KeyEvent.KEYCODE_F10: return "long";
            case KeyEvent.KEYCODE_DPAD_LEFT: case KeyEvent.KEYCODE_DPAD_UP: return "left";
            case KeyEvent.KEYCODE_DPAD_RIGHT: case KeyEvent.KEYCODE_DPAD_DOWN: return "right";
            default: return null;
        }
    }

    // ------------------------------------------------------------------ photo -> grade

    private void capture() {
        if (busy) { Log.i(TAG, "capture ignored, still busy"); return; }
        if (!has(Manifest.permission.CAMERA)) { js("worn.error(" + JSONObject.quote("No camera permission") + ")"); return; }
        busy = true;
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

    private void grade(byte[] jpeg) {
        try {
            long t0 = System.currentTimeMillis();
            String json = new Backend(api).grade(jpeg, null, null); // the backend uses the active session
            Log.i(TAG, "graded in " + (System.currentTimeMillis() - t0) + "ms: " + json);
            new JSONObject(json);
            done("worn.graded(" + JSONObject.quote(json) + ")");
        } catch (Backend.HttpError e) {
            Log.e(TAG, "grade http error", e);
            done("worn.error(" + JSONObject.quote(e.code == 503 ? "The checker is busy. Say check again." : "Server error " + e.code) + ")");
        } catch (Exception e) {
            Log.e(TAG, "grade failed", e);
            done("worn.error(" + JSONObject.quote("Can't reach the server. Say check again.") + ")");
        }
    }

    private void done(String script) { ui.post(() -> { busy = false; js(script); }); }

    // ------------------------------------------------------------------ web view

    private void setupWebView() {
        WebSettings ws = web.getSettings();
        ws.setJavaScriptEnabled(true);
        ws.setDomStorageEnabled(true);
        ws.setMediaPlaybackRequiresUserGesture(false);
        ws.setCacheMode(WebSettings.LOAD_NO_CACHE);
        web.setVerticalScrollBarEnabled(false);
        web.setHorizontalScrollBarEnabled(false);
        web.setFocusable(false); // keys come to the activity, not the page
        web.addJavascriptInterface(new Bridge(), "Native");
        web.setWebChromeClient(new WebChromeClient() {
            @Override public boolean onConsoleMessage(ConsoleMessage m) {
                Log.i("WornWeb", m.message() + " @" + m.sourceId() + ":" + m.lineNumber());
                return true;
            }
        });
        web.setWebViewClient(new WebViewClient() {
            @Override public void onPageFinished(WebView v, String url) { Log.i(TAG, "page loaded " + url); }
        });
    }

    private String asset(String name) {
        try (InputStream in = getAssets().open(name)) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buf = new byte[16384];
            int n;
            while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            return out.toString("UTF-8");
        } catch (Exception e) {
            Log.e(TAG, "asset " + name, e);
            return "<html><body style='background:#000;color:#fff'>missing " + name + "</body></html>";
        }
    }

    /** Our page, with the backend as its origin (same-origin fetches, B's /static/web scripts). */
    private void loadPage() {
        ui.removeCallbacks(retryLoad);
        pageReady = false;
        web.loadDataWithBaseURL(api + "/", asset("ui/index.html"), "text/html", "utf-8", null);
        Log.i(TAG, "loading app UI with base " + api);
    }

    private void showOffline() {
        pageReady = false;
        web.loadDataWithBaseURL(null,
                "<html><body style='background:#000;color:#8a8f98;font:24px sans-serif;text-align:center'>"
                        + "<h1 style='color:#fff;font-size:58px;margin-top:120px;letter-spacing:3px'>Worn</h1>"
                        + "<p>Looking for the lesson server…</p><p style='font-size:17px'>" + primary + "<br>or USB " + fallback + "</p></body></html>",
                "text/html", "utf-8", null);
        ui.removeCallbacks(retryLoad);
        ui.postDelayed(retryLoad, 3000);
    }

    private void js(String script) {
        ui.post(() -> {
            if (!pageReady && !script.startsWith("worn.boot")) return;
            web.evaluateJavascript("window.worn && " + script, null);
        });
    }

    private final class Bridge {
        /** The page is up; flush anything that waited for it. */
        @JavascriptInterface public void ready() {
            ui.post(() -> {
                pageReady = true;
                js("worn.mic(" + JSONObject.quote(mic.isRunning() ? "listening" : "off") + ")");
                if (pendingSay != null) { js("worn.heard(" + JSONObject.quote(pendingSay) + ")"); pendingSay = null; }
            });
        }
        @JavascriptInterface public void setScreen(String s) { if (s != null) screen = s; }
        @JavascriptInterface public void speak(String text) {
            if (text == null || text.trim().isEmpty() || api == null) return;
            String url = api + "/say?text=" + Uri.encode(text.trim());
            ui.post(() -> playUrl(url));
        }
        @JavascriptInterface public void play(String url) {
            String u = abs(url);
            if (u != null) ui.post(() -> playUrl(u));
        }
        /** Mute the mic for a moment (the page is about to play a sound effect). */
        @JavascriptInterface public void quiet(int ms) { mic.resume(Math.max(0, ms)); }
        @JavascriptInterface public void stopAudio() { ui.post(MainActivity.this::stopAudio); }
        @JavascriptInterface public void listen(boolean on) {
            wantMic = on;
            ui.post(() -> { if (on) startMic(); else mic.stop(); });
        }
        /** Watch the paper for new strokes (lesson "your turn"). */
        @JavascriptInterface public void watchInk(boolean on) {
            if (inkWatch.enabled != on) Log.i(TAG, "ink watch " + (on ? "on" : "off"));
            inkWatch.enabled = on;
            if (on) inkWatch.reset();
        }
        @JavascriptInterface public void capture() { ui.post(MainActivity.this::capture); }
        @JavascriptInterface public String backend() { return api; }
        @JavascriptInterface public String via() { return api != null && api.equals(primary) ? "wifi" : "usb"; }
    }

    // ------------------------------------------------------------------ misc

    private boolean has(String perm) { return checkSelfPermission(perm) == PackageManager.PERMISSION_GRANTED; }

    private void hideSystemUi() {
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_FULLSCREEN
                | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                | View.SYSTEM_UI_FLAG_LAYOUT_STABLE);
    }
}
