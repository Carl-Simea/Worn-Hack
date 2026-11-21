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
    }

    private static final String TAG = "WornVoice";
    static final int RATE = 16000;
    private static final int FRAME = 320;              // 20 ms
    private static final int START_FRAMES = 3;         // 60 ms of voice to start
    private static final int END_FRAMES = 38;          // 760 ms of quiet to end
    private static final int PREROLL_FRAMES = 20;      // 400 ms kept from before the start
    private static final int MIN_FRAMES = 18;          // 360 ms minimum
    private static final int MAX_FRAMES = 350;         // 7 s maximum

    private final Callback cb;
    private volatile boolean running;
    private volatile long mutedUntil;
    private volatile boolean paused;
    private Thread thread;
    private String state = "";
    /** Average loudness (RMS over the voiced frames) an utterance needs. The wearer's mouth is ~5 cm from
     *  the mic; people talking nearby are much quieter. Tunable live: --ei loud 2500 */
    volatile int minLoud = 1800;

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
    void pause() { paused = true; }
    /** Unmute, after a short tail so the end of our audio isn't heard. */
    void resume(long tailMs) { mutedUntil = System.currentTimeMillis() + tailMs; paused = false; }

    private boolean muted() { return paused || System.currentTimeMillis() < mutedUntil; }

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
        ByteArrayOutputStream pcm = new ByteArrayOutputStream(RATE * 2 * 4);
        long lastLevel = 0;
        setState("listening");
        try {
            while (running) {
                int n = rec.read(frame, 0, FRAME);
                if (n <= 0) continue;
                double sum = 0;
                for (int i = 0; i < n; i++) sum += (double) frame[i] * frame[i];
                float rms = (float) Math.sqrt(sum / n);

                if (muted()) {
                    if (inSpeech) { inSpeech = false; pcm.reset(); }
                    voiced = 0;
                    setState("listening");
                    continue;
                }
                long now = System.currentTimeMillis();
                if (now - lastLevel > 1000) { lastLevel = now; cb.onLevel(rms, floor); }

                float startT = Math.max(floor * 2.6f, 450f);
                float keepT = Math.max(floor * 1.8f, 300f);
                if (!inSpeech) {
                    // Track the room's noise floor while nobody is talking.
                    floor = rms < floor ? floor * 0.9f + rms * 0.1f : floor * 0.995f + rms * 0.005f;
                    ring[ringPos] = frame.clone();
                    ringPos = (ringPos + 1) % PREROLL_FRAMES;
                    voiced = rms > startT ? voiced + 1 : 0;
                    if (voiced >= START_FRAMES) {
                        inSpeech = true;
                        loudSum = 0; loudN = 0; peak = 0;
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
                    quiet = rms > keepT ? 0 : quiet + 1;
                    if (rms > keepT) { loudSum += rms; loudN++; }
                    if (rms > peak) peak = rms;
                    if (quiet >= END_FRAMES || frames >= MAX_FRAMES) {
                        inSpeech = false;
                        voiced = 0;
                        int speechFrames = frames - quiet - PREROLL_FRAMES;
                        setState("listening");
                        int loud = loudN == 0 ? 0 : (int) (loudSum / loudN);
                        Log.i(TAG, "utterance " + (frames * 20) + "ms loud=" + loud + " peak=" + (int) peak + " floor=" + (int) floor
                                + (loud < minLoud ? " (too quiet, ignored)" : ""));
                        if (loud < minLoud) { /* someone else talking nearby */ }
                        else if (speechFrames >= MIN_FRAMES - PREROLL_FRAMES / 2) {
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
