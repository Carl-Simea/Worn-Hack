package com.worn.glasses;

import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import android.util.Log;

import java.io.ByteArrayOutputStream;

/**
 * Always-on listening on the glasses' microphone. A simple energy detector cuts the stream into
 * utterances (start after ~60 ms above the noise floor, end after ~750 ms of quiet, 0.35–7 s long,
 * with 400 ms of audio from before the start so the first syllable isn't lost). Each utterance is
 * handed over as a 16 kHz mono 16-bit WAV.
 *
 * pause()/resume() mute it while the glasses' own speaker plays, so Worn doesn't hear itself.
 */
final class VoiceListener {
    interface Callback {
        /** state: "listening" | "hearing" | "off" */
        void onState(String state);
        void onUtterance(byte[] wav, int ms);
        void onLevel(float rms, float floor);
        /** The wearer started talking over Scribi: stop the speaker; capture has already started. */
        void onBargeIn(float rms, float echo);
    }

    private static final String TAG = "WornVoice";
    static final int RATE = 16000;
    private static final int FRAME = 320;              // 20 ms
    private static final int START_FRAMES = 3;         // 60 ms of voice to start
    private static final int END_FRAMES = 35;          // 700 ms of quiet to end (no clipped words)
    private static final int PREROLL_FRAMES = 20;      // 400 ms kept from before the start
    private static final int MIN_FRAMES = 18;          // 360 ms minimum
    private static final int MAX_FRAMES = 350;         // 7 s maximum

    private final Callback cb;
    private volatile boolean running;
    private volatile long mutedUntil;
    private volatile boolean paused;
    private volatile Thread thread;
    private String state = "";
    /** Average loudness (RMS over the voiced frames) an utterance needs. The wearer's mouth is ~5 cm from
     *  the mic; people talking nearby are much quieter. Tunable live: --ei loud 2500 */
    volatile int minLoud = 1000;   // wearer measured ~1700 (80th pct), room chatter ~400–700

    VoiceListener(Callback cb) { this.cb = cb; }

    void start() {
        if (running) return;
        running = true;
        thread = new Thread(this::loop, "worn-mic");
        thread.start();
    }

    void stop() {
        running = false;
        if (thread != null) thread.interrupt();
        thread = null;
    }

    boolean isRunning() { return running; }

    /** Mute while our own audio plays. */
    void pause() {
        if (!paused) { echoEnv = 0; bargeRun = 0; }
        paused = true; pausedAt = System.currentTimeMillis();
    }
    // Barge-in while our speaker plays: the speaker's echo at the mic is learned (slow envelope); a voice clearly
    // above it (≥ BARGE_RATIO × echo and ≥ bargeMin) for 200 ms means the wearer is talking.
    volatile boolean bargeEnabled = true;
    volatile int bargeMin = 3000;
    private static final float BARGE_RATIO = 2.5f;
    private static final int BARGE_FRAMES = 6;        // 120 ms of the wearer's voice → stop Scribi
    private float echoEnv; private int bargeRun; private long lastEchoLog;
    volatile long bargeStart;   // when the voice that triggered the last barge-in began (for latency logs)
    private volatile long pausedAt;
    /** Unmute, after a short tail so the end of our audio isn't heard. */
    void resume(long tailMs) { mutedUntil = System.currentTimeMillis() + tailMs; paused = false; }

    private boolean muted() {
        long now = System.currentTimeMillis();
        // Watchdog: a clip that never reports "done" must not leave Worn deaf.
        if (paused && now - pausedAt > 15000) { Log.w(TAG, "mute watchdog: unmuting"); paused = false; }
        return paused || now < mutedUntil;
    }

    private void setState(String s) {
        if (s.equals(state)) return;
        state = s;
        cb.onState(s);
    }

    private void loop() {
        int min = AudioRecord.getMinBufferSize(RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
        AudioRecord rec;
        try {
            rec = new AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, RATE, AudioFormat.CHANNEL_IN_MONO,
                    AudioFormat.ENCODING_PCM_16BIT, Math.max(min, FRAME * 2 * 25));
            if (rec.getState() != AudioRecord.STATE_INITIALIZED) {
                rec.release();
                rec = new AudioRecord(MediaRecorder.AudioSource.MIC, RATE, AudioFormat.CHANNEL_IN_MONO,
                        AudioFormat.ENCODING_PCM_16BIT, Math.max(min, FRAME * 2 * 25));
            }
            rec.startRecording();
        } catch (Exception e) {
            Log.e(TAG, "mic failed", e);
            running = false;
            setState("off");
            return;
        }
        Log.i(TAG, "mic on, state=" + rec.getRecordingState());
        short[] frame = new short[FRAME];
        short[][] ring = new short[PREROLL_FRAMES][];
        int ringPos = 0;
        float floor = 300f;
        int voiced = 0, quiet = 0, frames = 0;
        boolean inSpeech = false;
        double loudSum = 0; int loudN = 0; float peak = 0;
        float[] recent = new float[100];   // last 2 s of levels outside speech
        int recentPos = 0, recentN = 0;
        float[] sorted = new float[100];
        float env = 0, peakEnv = 0;
        float[] levels = new float[MAX_FRAMES + PREROLL_FRAMES + 2]; int levelN = 0;
        ByteArrayOutputStream pcm = new ByteArrayOutputStream(RATE * 2 * 4);
        long lastLevel = 0;
        setState("listening");
        try {
            final Thread me = Thread.currentThread();
            while (running && thread == me) {     // a restarted listener retires the old thread (never two mics)
                int n = rec.read(frame, 0, FRAME);
                if (n <= 0) continue;
                double sum = 0;
                for (int i = 0; i < n; i++) sum += (double) frame[i] * frame[i];
                float rms = (float) Math.sqrt(sum / n);

                if (muted()) {
                    boolean barged = false;
                    long nowM = System.currentTimeMillis();
                    if (paused && bargeEnabled) {
                        ring[ringPos] = frame.clone();
                        ringPos = (ringPos + 1) % PREROLL_FRAMES;
                        boolean learning = nowM - pausedAt < 300;
                        echoEnv = echoEnv == 0 ? rms : echoEnv * 0.97f + Math.min(rms, Math.max(echoEnv, 300f) * 3f) * 0.03f;
                        float bargeT = Math.max(bargeMin, echoEnv * BARGE_RATIO);
                        if (!learning && rms > bargeT) { if (bargeRun == 0) bargeStart = nowM; bargeRun++; } else bargeRun = 0;
                        if (nowM - lastEchoLog > 500) { lastEchoLog = nowM; Log.v(TAG, "speaking: rms " + (int) rms + " echo " + (int) echoEnv + " barge>" + (int) bargeT); }
                        if (bargeRun >= BARGE_FRAMES) {
                            Log.i(TAG, "barge-in: rms " + (int) rms + " over echo " + (int) echoEnv);
                            cb.onBargeIn(rms, echoEnv);
                            paused = false; mutedUntil = 0; bargeRun = 0;
                            voiced = START_FRAMES - 1;   // the next frame opens the utterance (with the pre-roll ring)
                            barged = true;
                        }
                    }
                    if (!barged) {
                        if (inSpeech) { inSpeech = false; pcm.reset(); }
                        voiced = 0;
                        setState("listening");
                        continue;
                    }
                }
                long now = System.currentTimeMillis();
                if (now - lastLevel > 1000) { lastLevel = now; cb.onLevel(rms, floor); }

                float startT = Math.max(floor * 2.6f, 450f);
                // The end of speech is judged against the speaker's own level too, so a noisy room
                // (other people talking) can't hold an utterance open.
                float speechMean = loudN == 0 ? 0 : (float) (loudSum / loudN);
                float keepT = Math.max(Math.max(floor * 1.8f, 300f), speechMean * 0.33f);
                if (!inSpeech) {
                    // Noise floor = 25th percentile of the last 2 s: follows the room up and down.
                    recent[recentPos] = rms; recentPos = (recentPos + 1) % recent.length; if (recentN < recent.length) recentN++;
                    System.arraycopy(recent, 0, sorted, 0, recentN);
                    java.util.Arrays.sort(sorted, 0, recentN);
                    floor = Math.max(60f, sorted[recentN / 4]);
                    ring[ringPos] = frame.clone();
                    ringPos = (ringPos + 1) % PREROLL_FRAMES;
                    voiced = rms > startT ? voiced + 1 : 0;
                    if (voiced >= START_FRAMES) {
                        inSpeech = true;
                        loudSum = 0; loudN = 0; peak = 0; env = rms; peakEnv = rms; levelN = 0;
                        quiet = 0;
                        frames = 0;
                        pcm.reset();
                        for (int k = 0; k < PREROLL_FRAMES; k++) {
                            short[] f = ring[(ringPos + k) % PREROLL_FRAMES];
                            if (f != null) { write(pcm, f, f.length); frames++; }
                        }
                        setState("hearing");
                    }
                } else {
                    write(pcm, frame, n);
                    frames++;
                    env = env * 0.75f + rms * 0.25f;          // ~80 ms smoothing
                    if (env > peakEnv) peakEnv = env;
                    if (levelN < levels.length) levels[levelN++] = rms;
                    // Quiet = well below this speaker's own peak (or near the floor).
                    quiet = env > Math.max(keepT, peakEnv * 0.22f) ? 0 : quiet + 1;
                    if (rms > Math.max(floor * 1.8f, 300f)) { loudSum += rms; loudN++; }
                    if (rms > peak) peak = rms;
                    if (quiet >= END_FRAMES || frames >= MAX_FRAMES) {
                        inSpeech = false;
                        voiced = 0;
                        int speechFrames = frames - quiet - PREROLL_FRAMES;
                        setState("listening");
                        java.util.Arrays.sort(levels, 0, levelN);
                        int loud = levelN == 0 ? 0 : (int) levels[(int) (levelN * 0.8f)];   // 80th percentile
                        Log.i(TAG, "utterance " + (frames * 20) + "ms loud=" + loud + " peak=" + (int) peak + " floor=" + (int) floor
                                + (loud < minLoud ? " (too quiet, ignored)" : ""));
                        if (loud < minLoud) { /* someone else talking nearby */ }
                        else if (speechFrames >= 6) {          // ≥ 120 ms of actual voice ("help", "next")
                            byte[] raw = pcm.toByteArray();
                            cb.onUtterance(wav(raw), raw.length * 1000 / (RATE * 2));
                        } else {
                            Log.d(TAG, "too short, dropped (" + speechFrames + " frames)");
                        }
                        pcm.reset();
                        java.util.Arrays.fill(ring, null);
                    }
                }
            }
        } finally {
            try { rec.stop(); } catch (Exception ignored) { }
            rec.release();
            setState("off");
            Log.i(TAG, "mic off");
        }
    }

    private static void write(ByteArrayOutputStream out, short[] f, int n) {
        for (int i = 0; i < n; i++) { out.write(f[i] & 0xff); out.write((f[i] >> 8) & 0xff); }
    }

    static byte[] wav(byte[] pcm) {
        ByteArrayOutputStream o = new ByteArrayOutputStream(pcm.length + 44);
        int byteRate = RATE * 2;
        str(o, "RIFF"); int32(o, 36 + pcm.length); str(o, "WAVE");
        str(o, "fmt "); int32(o, 16); int16(o, 1); int16(o, 1); int32(o, RATE); int32(o, byteRate); int16(o, 2); int16(o, 16);
        str(o, "data"); int32(o, pcm.length);
        o.write(pcm, 0, pcm.length);
        return o.toByteArray();
    }

    private static void str(ByteArrayOutputStream o, String s) { for (int i = 0; i < s.length(); i++) o.write(s.charAt(i)); }
    private static void int32(ByteArrayOutputStream o, int v) { o.write(v); o.write(v >> 8); o.write(v >> 16); o.write(v >> 24); }
    private static void int16(ByteArrayOutputStream o, int v) { o.write(v); o.write(v >> 8); }
}
