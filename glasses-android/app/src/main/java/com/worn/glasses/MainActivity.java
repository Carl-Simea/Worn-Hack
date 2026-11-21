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
    private final ExecutorService tier2 = Executors.newSingleThreadExecutor(); // /stroke-match

    private WebView web;
    private GlassesCamera camera;
    private MediaActionSound shutter;
    private VoiceListener mic;
    private InkWatcher inkWatch;
    private final CameraStream camStream = new CameraStream();
    private volatile String camWs;    // explicit stream URL (--es camws), else derived from the backend
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
        // A bug on a worker thread (camera, mic, network) must not take the whole app (the glasses' home) down.
        final Thread.UncaughtExceptionHandler sys = Thread.getDefaultUncaughtExceptionHandler();
        Thread.setDefaultUncaughtExceptionHandler((t, ex) -> {
            if (t == Looper.getMainLooper().getThread()) { if (sys != null) sys.uncaughtException(t, ex); return; }
            Log.e(TAG, "worker thread " + t.getName() + " died (app keeps running)", ex);
        });
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
        camera.setStream(camStream);
        mic = new VoiceListener(new VoiceListener.Callback() {
            @Override public void onState(String s) { js("worn.mic(" + JSONObject.quote(s) + ")"); }
            @Override public void onUtterance(byte[] wav, int ms) { sendVoice(wav, ms); }
            @Override public void onBargeIn(float rms, float echo) { ui.post(MainActivity.this::bargeIn); }
            @Override public void onLevel(float rms, float floor) {
                Log.v("WornVoice", "rms " + (int) rms + " floor " + (int) floor);
            }
        });
        initTts();
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
        if (intent != null && intent.hasExtra("camws")) p.edit().putString("camws", intent.getStringExtra("camws").trim()).apply();
        camWs = p.getString("camws", "");
        String nextPrimary = p.getString("api", BuildConfig.DEFAULT_API).replaceAll("/+$", "");
        String nextFallback = p.getString("fallback", USB_FALLBACK).replaceAll("/+$", "");
        boolean changed = !nextPrimary.equals(primary) || !nextFallback.equals(fallback);
        primary = nextPrimary;
        fallback = nextFallback;
        if (changed || !pageReady) {
            Log.i(TAG, "backend " + primary + " (fallback " + fallback + ")");
            chooseAndLoad();
        }
        if (intent != null && intent.hasExtra("loud")) p.edit().putInt("loud", intent.getIntExtra("loud", 1000)).apply();
        mic.minLoud = p.getInt("loud", 1000);
        if (intent != null && intent.hasExtra("barge")) p.edit().putInt("barge", intent.getIntExtra("barge", 3000)).apply();
        mic.bargeMin = p.getInt("barge", 3000);
        String say = intent == null ? null : intent.getStringExtra("say");
        if (say != null && !say.isEmpty()) {
            if (pageReady) js("worn.heard(" + JSONObject.quote(say) + ")"); else pendingSay = say;
        }
        String r64 = intent == null ? null : intent.getStringExtra("reply64"); // debug: feed a /voice reply (base64 JSON)
        if (r64 != null && pageReady) {
            try {
                String json = new String(android.util.Base64.decode(r64, android.util.Base64.DEFAULT), "UTF-8");
                js("worn.voice(" + JSONObject.quote(json) + ")");
            } catch (Exception e) { Log.w(TAG, "reply64", e); }
        }
        if (intent != null) intent.removeExtra("reply64");
        String dbg = intent == null ? null : intent.getStringExtra("js");   // debug: run page script
        if (dbg != null && pageReady) js(dbg);
        if (intent != null) intent.removeExtra("js");
        if (intent != null && intent.getBooleanExtra("stockhome", false)) { intent.removeExtra("stockhome"); openStockLauncher(); }
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
        if (api != null) startStream();
        if (wantMic) startMic();
    }

    @Override
    protected void onPause() {
        mic.stop();
        camStream.stop();
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
        tier2.shutdownNow();
        beat.shutdown();
        if (shutter != null) shutter.release();
        if (tts != null) tts.shutdown();
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
        final int seq = ++voiceSeq;
        if (a == null) return;
        js("worn.mic('thinking')");
        talk.execute(() -> {
            long t0 = System.currentTimeMillis();
            try {
                String json = new Backend(a).voice(wav, s);
                Log.i(TAG, "voice " + ms + "ms audio -> " + (System.currentTimeMillis() - t0) + "ms: " + json);
                if (seq <= staleUpTo) { Log.i(TAG, "dropped stale reply #" + seq + " (interrupted)"); return; }
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

    /** One thing to play: a pronunciation clip, or a line of Scribi's (speech: has text, falls back, drives the face). */
    private static final class Item {
        final String url, text; final boolean speech; int attempt;
        Item(String url, String text, boolean speech) { this.url = url; this.text = text; this.speech = speech; }
    }
    private final ArrayDeque<Item> audioQueue = new ArrayDeque<>();
    private MediaPlayer player;
    private Item current;
    private android.speech.tts.TextToSpeech tts;
    private boolean ttsReady;
    private boolean ttsSpeaking;

    private void playUrl(String url) { enqueue(new Item(url, null, false)); }

    /** Scribi says `text`: the backend's audio (url) first, then /say?text=, then Android TTS. */
    private void speakLine(String url, String text) {
        if ((url == null || url.isEmpty()) && api != null && text != null) url = api + "/say?text=" + Uri.encode(text);
        enqueue(new Item(url, text, true));
    }

    private void enqueue(Item it) {
        audioQueue.add(it);
        if (player == null && !ttsSpeaking) playNext();
    }

    private void playNext() {
        Item it = audioQueue.poll();
        current = it;
        if (it == null) {
            mic.resume(300);
            js("worn.talk('end')");
            js("worn.audioDone()");
            return;
        }
        mic.pause();   // listening for barge-in only, nothing is sent while Scribi talks
        if (it.speech) js("worn.talk('start'," + JSONObject.quote(it.text == null ? "" : it.text) + ")");
        if (it.url == null || it.url.isEmpty()) { fallback(it); return; }
        MediaPlayer mp = new MediaPlayer();
        player = mp;
        try {
            mp.setAudioAttributes(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build());
            mp.setDataSource(it.url);
            mp.setOnPreparedListener(MediaPlayer::start);
            mp.setOnCompletionListener(m -> finishPlayer(m));
            mp.setOnErrorListener((m, what, extra) -> {
                Log.w(TAG, "audio error " + what + " " + it.url);
                releaseQuietly(m); if (player == m) player = null;
                ui.post(() -> fallback(it));
                return true;
            });
            mp.prepareAsync();
            ui.postDelayed(() -> { if (player == mp && !mp.isPlaying()) { Log.w(TAG, "audio stuck " + it.url); releaseQuietly(mp); player = null; fallback(it); } }, 8000);
        } catch (Exception e) {
            Log.w(TAG, "audio failed " + it.url, e);
            releaseQuietly(mp); player = null;
            fallback(it);
        }
    }

    /** Speech that couldn't play: try /say, then the device's own TTS; clips are just skipped. */
    private void fallback(Item it) {
        if (current != it) return;
        if (it.speech && it.text != null && !it.text.isEmpty()) {
            String say = api == null ? null : api + "/say?text=" + Uri.encode(it.text);
            if (it.attempt == 0 && say != null && !say.equals(it.url)) {
                it.attempt = 1;
                Item retry = new Item(say, it.text, true); retry.attempt = 1;
                audioQueue.addFirst(retry);
                ui.post(this::playNext);
                return;
            }
            if (ttsReady) {
                ttsSpeaking = true;
                tts.speak(it.text, android.speech.tts.TextToSpeech.QUEUE_FLUSH, null, "scribi");
                return;   // onDone → playNext
            }
        }
        ui.post(this::playNext);
    }

    private void finishPlayer(MediaPlayer m) {
        releaseQuietly(m);
        if (player == m) player = null;
        ui.post(() -> { if (player == null && !ttsSpeaking) playNext(); });
    }

    private static void releaseQuietly(MediaPlayer m) { try { m.release(); } catch (Exception ignored) { } }

    private void stopAudio() {
        audioQueue.clear();
        current = null;
        MediaPlayer m = player;
        player = null;
        if (m != null) { try { m.stop(); } catch (Exception ignored) { } releaseQuietly(m); }
        if (ttsSpeaking && tts != null) { tts.stop(); ttsSpeaking = false; }
        mic.resume(250);
        js("worn.talk('end')");
    }

    /** Barge-in: the wearer talked over Scribi. Stop at once; the mic is already capturing the new utterance. */
    private int voiceSeq;              // utterances sent to /voice
    private volatile int staleUpTo;    // replies to utterances up to this one are dropped (said before a barge-in)

    private void bargeIn() {
        staleUpTo = voiceSeq;          // anything still in flight belongs to the interrupted exchange
        audioQueue.clear();
        current = null;
        MediaPlayer m = player;
        player = null;
        if (m != null) { try { m.stop(); } catch (Exception ignored) { } releaseQuietly(m); }
        if (ttsSpeaking && tts != null) { tts.stop(); ttsSpeaking = false; }
        js("worn.talk('barge')");
        Log.i(TAG, "barge-in: Scribi stopped " + (System.currentTimeMillis() - mic.bargeStart) + " ms after the wearer started talking");
    }

    private void initTts() {
        tts = new android.speech.tts.TextToSpeech(this, status -> {
            ttsReady = status == android.speech.tts.TextToSpeech.SUCCESS;
            if (ttsReady) {
                tts.setLanguage(java.util.Locale.US);
                tts.setOnUtteranceProgressListener(new android.speech.tts.UtteranceProgressListener() {
                    @Override public void onStart(String id) { }
                    @Override public void onDone(String id) { ui.post(() -> { ttsSpeaking = false; playNext(); }); }
                    @Override public void onError(String id) { ui.post(() -> { ttsSpeaking = false; playNext(); }); }
                });
            }
            Log.i(TAG, "android tts " + (ttsReady ? "ready" : "not available (backend voice only)"));
        });
    }

    private String abs(String u) {
        if (u == null) return null;
        if (u.startsWith("http://") || u.startsWith("https://")) return u;
        return api + (u.startsWith("/") ? u : "/" + u);
    }

    // ------------------------------------------------------------------ keys (backup)

    /** Way out of demo mode: hold Back for 3 s → the glasses' own launcher. A short Back = back inside Worn. */
    private static final String STOCK_HOME = "com.mlaixr.launcher/.MainActivity";
    private boolean backHeld, backFired;
    private final Runnable backLong = () -> {
        backFired = true;
        Log.i(TAG, "Back held 3 s: opening the stock launcher");
        openStockLauncher();
    };

    private void openStockLauncher() {
        try {
            Intent i = new Intent(Intent.ACTION_MAIN);
            i.addCategory(Intent.CATEGORY_HOME);
            i.setComponent(android.content.ComponentName.unflattenFromString(STOCK_HOME));
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(i);
        } catch (Exception ex) {
            Log.w(TAG, "stock launcher", ex);
            js("worn.toastMsg && worn.toastMsg('Could not open the glasses launcher')");
        }
    }

    @Override
    public boolean dispatchKeyEvent(KeyEvent e) {
        int code = e.getKeyCode();
        if (e.getAction() == KeyEvent.ACTION_DOWN) {
            Log.i(KEYS, "down " + KeyEvent.keyCodeToString(code) + " (" + code + ") repeat=" + e.getRepeatCount());
        }
        if (code == KeyEvent.KEYCODE_BACK) {
            if (e.getAction() == KeyEvent.ACTION_DOWN && e.getRepeatCount() == 0) {
                backHeld = true; backFired = false;
                ui.postDelayed(backLong, 3000);
            } else if (e.getAction() == KeyEvent.ACTION_UP) {
                ui.removeCallbacks(backLong);
                if (backHeld && !backFired && !e.isCanceled()) js("worn.key('double')");   // short press: back in Worn
                backHeld = false;
            }
            return true;   // never finish: Worn may be the home app
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

    private int captureRetries;

    private volatile String gradeChar, gradeLang;   // sent with /grade so a backend restart (lost session) can't break a check

    private void capture() {
        if (busy) { Log.i(TAG, "capture ignored, still busy"); return; }
        if (!has(Manifest.permission.CAMERA)) { js("worn.error(" + JSONObject.quote("No camera permission") + ")"); return; }
        busy = true;
        camera.takePicture(new GlassesCamera.Callback() {
            @Override public void onJpeg(byte[] jpeg) {
                ui.post(() -> shutter.play(MediaActionSound.SHUTTER_CLICK));
                captureRetries = 0;
                js("worn.captured()");
                net.execute(() -> grade(jpeg));
            }
            @Override public void onError(String message) {
                Log.w(TAG, "camera: " + message);
                // A stroke photo may still be in flight: wait for it rather than failing the check.
                if (message != null && message.startsWith("Still") && captureRetries++ < 6) {
                    ui.postDelayed(() -> { busy = false; capture(); }, 500);
                    return;
                }
                ui.post(() -> { busy = false; captureRetries = 0; js("worn.error(" + JSONObject.quote(message) + ")"); });
            }
        });
    }

    private void grade(byte[] jpeg) {
        try {
            long t0 = System.currentTimeMillis();
            String json = new Backend(api).grade(jpeg, gradeChar, gradeLang);
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

    /** One photo after a stroke → POST /stroke-match → worn.strokeScore(json | null). Skipped while a check runs. */
    private void strokeShot(int index, String ch, String lang) {
        if (busy || !has(Manifest.permission.CAMERA)) { js("worn.strokeScore(" + index + ",null)"); return; }
        camera.takePicture(new GlassesCamera.Callback() {
            @Override public void onJpeg(byte[] jpeg) {
                final String a = api;
                tier2.execute(() -> {
                    long t0 = System.currentTimeMillis();
                    try {
                        String json = new Backend(a).strokeMatch(jpeg, index, ch, lang);
                        Log.i(TAG, "stroke " + index + " matched in " + (System.currentTimeMillis() - t0) + "ms: " + json);
                        js("worn.strokeScore(" + index + "," + JSONObject.quote(json) + ")");
                    } catch (Exception e) {
                        Log.w(TAG, "stroke-match " + index + ": " + e.getMessage());
                        js("worn.strokeScore(" + index + ",null)");
                    }
                });
            }
            @Override public void onError(String message) { js("worn.strokeScore(" + index + ",null)"); }
        });
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
            /** /__app/… is served from the APK's assets (bundled Noto fonts for the five non-Latin scripts). */
            @Override public android.webkit.WebResourceResponse shouldInterceptRequest(WebView v, android.webkit.WebResourceRequest req) {
                Uri u = req.getUrl();
                String path = u.getPath();
                if (path == null || !path.startsWith("/__app/")) return null;
                String name = path.substring("/__app/".length());
                if (name.contains("..")) return null;
                try {
                    String mime = name.endsWith(".ttf") ? "font/ttf" : name.endsWith(".otf") ? "font/otf" : name.endsWith(".woff2") ? "font/woff2"
                            : name.endsWith(".css") ? "text/css" : name.endsWith(".js") ? "application/javascript" : "application/octet-stream";
                    android.webkit.WebResourceResponse r = new android.webkit.WebResourceResponse(mime, null, getAssets().open(name));
                    java.util.Map<String, String> h = new java.util.HashMap<>();
                    h.put("Access-Control-Allow-Origin", "*");
                    h.put("Cache-Control", "max-age=86400");
                    r.setResponseHeaders(h);
                    return r;
                } catch (Exception e) {
                    Log.w(TAG, "asset " + name + ": " + e.getMessage());
                    return null;
                }
            }
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
    /** Live camera: --es camws ws://host:port/path, or "off"; default = the backend's /ws/camera (A).
     *  The reference relay is --es camws ws://127.0.0.1:8790/glasses/camera/ws (tools/camera_relay.py). */
    private void startStream() {
        String u = camWs;
        if ("off".equals(u)) { camStream.stop(); return; }
        if (api == null) return;
        if (u == null || u.isEmpty()) {
            // A's backend relay: WS /ws/camera?role=pub (feeds /live and the automatic grading)
            Uri b = Uri.parse(api);
            u = "ws://" + b.getHost() + ":" + (b.getPort() > 0 ? b.getPort() : 80) + "/ws/camera?role=pub";
        }
        camStream.setHttpBase(api);
        camStream.start(u);
    }

    private void loadPage() {
        ui.removeCallbacks(retryLoad);
        startStream();
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
            if (text == null || text.trim().isEmpty()) return;
            String t = text.trim();
            ui.post(() -> speakLine(null, t));
        }
        /** Scribi's line with the backend's own audio (audio_url / say_url); text is the caption + fallback. */
        @JavascriptInterface public void speakUrl(String url, String text) {
            String u = abs(url), t = text == null ? "" : text.trim();
            ui.post(() -> speakLine(u, t));
        }
        @JavascriptInterface public void bargeIn(boolean on) { mic.bargeEnabled = on; }
        /** A new reply from Scribi replaces anything still queued or playing (no stale lines). */
        @JavascriptInterface public void speakNow(String url, String text) {
            String u = abs(url), t = text == null ? "" : text.trim();
            ui.post(() -> { audioQueue.clear(); MediaPlayer m = player; player = null; current = null;
                if (m != null) { try { m.stop(); } catch (Exception ignored) { } releaseQuietly(m); }
                if (ttsSpeaking && tts != null) { tts.stop(); ttsSpeaking = false; }
                speakLine(u, t); });
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
        @JavascriptInterface public void strokeShot(int index, String ch, String lang) { ui.post(() -> strokeShot(index, ch, lang)); }
        @JavascriptInterface public void capture() { ui.post(MainActivity.this::capture); }
        @JavascriptInterface public void captureFor(String ch, String lang) {
            gradeChar = ch == null || ch.isEmpty() ? null : ch;
            gradeLang = lang == null || lang.isEmpty() ? null : lang;
            ui.post(MainActivity.this::capture);
        }
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
