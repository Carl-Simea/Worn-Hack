package com.worn.glasses;

/**
 * Tier 1 on the glasses: "did a new stroke appear on the paper?" from 64×64 grayscale thumbnails of the
 * camera preview (same idea as the iPhone's InkDiff). Paper level = 70th percentile; ink = darker than
 * 0.62 × paper. New ink = ink now that wasn't near ink before (the old ink mask is dilated by 1 px so small
 * head jitter along existing strokes doesn't count), and it must still be there in the next frame, so a
 * passing hand or pen shadow doesn't count either. A big change (the head turned) resets the baseline.
 */
final class InkWatcher {
    interface Listener { void onNewStroke(float frac, int ms); }

    private static final int S = GlassesCamera.THUMB;
    private static final float STROKE_MIN = 0.0035f;  // ≥ ~14 of 4096 pixels
    private static final float SCENE_CHANGE = 0.18f;  // more than this = the view moved, not a stroke
    private static final long COOLDOWN_MS = 900;

    private final Listener listener;
    private boolean[] base;      // ink seen so far
    private boolean[] pending;   // candidate new ink from the previous frame
    private long lastFire;
    volatile boolean enabled;

    InkWatcher(Listener l) { listener = l; }

    void reset() { base = null; pending = null; }

    void onFrame(byte[] g) {
        if (!enabled) { base = null; pending = null; return; }
        long t0 = System.nanoTime();
        boolean[] ink = mask(g);
        if (base == null) { base = ink; pending = null; return; }
        boolean[] near = dilate(base);
        boolean[] cand = new boolean[S * S];
        int candN = 0;
        for (int i = 0; i < cand.length; i++) if (ink[i] && !near[i]) { cand[i] = true; candN++; }
        float candFrac = candN / (float) (S * S);
        if (candFrac > SCENE_CHANGE) { base = ink; pending = null; return; }   // looked somewhere else
        int stay = 0;
        if (pending != null) for (int i = 0; i < cand.length; i++) if (cand[i] && pending[i]) stay++;
        float frac = stay / (float) (S * S);
        long now = System.currentTimeMillis();
        if (frac >= STROKE_MIN && now - lastFire > COOLDOWN_MS) {
            lastFire = now;
            for (int i = 0; i < base.length; i++) base[i] = base[i] || ink[i];
            pending = null;
            listener.onNewStroke(frac, (int) ((System.nanoTime() - t0) / 1_000_000));
            return;
        }
        pending = cand;
    }

    private static boolean[] mask(byte[] g) {
        int[] hist = new int[256];
        for (byte b : g) hist[b & 0xff]++;
        int target = (int) (g.length * 0.70), acc = 0, paper = 255;
        for (int v = 0; v < 256; v++) { acc += hist[v]; if (acc >= target) { paper = v; break; } }
        int cut = (int) (paper * 0.62f);
        boolean[] m = new boolean[g.length];
        if (paper < 60) return m;   // too dark to see a page
        for (int i = 0; i < g.length; i++) m[i] = (g[i] & 0xff) < cut;
        return m;
    }

    private static boolean[] dilate(boolean[] m) {
        boolean[] d = new boolean[m.length];
        for (int y = 0; y < S; y++) for (int x = 0; x < S; x++) {
            if (!m[y * S + x]) continue;
            for (int dy = -1; dy <= 1; dy++) for (int dx = -1; dx <= 1; dx++) {
                int yy = y + dy, xx = x + dx;
                if (yy >= 0 && yy < S && xx >= 0 && xx < S) d[yy * S + xx] = true;
            }
        }
        return d;
    }
}
