package com.worn.glasses;

import android.graphics.ImageFormat;
import android.graphics.Rect;
import android.graphics.YuvImage;
import android.media.Image;
import android.os.SystemClock;
import android.util.Base64;
import android.util.Log;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.net.URI;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Live camera to the backend: preview frames (640×480 YUV) → JPEG q50 → one persistent WebSocket, ~12 fps.
 *
 *  - Never queues: the camera thread copies a frame only when the encoder is free and it's time for one;
 *    the encoder hands its JPEG to a one-slot mailbox; the sender always takes the newest. A slow socket
 *    just means older frames are overwritten (counted as dropped).
 *  - Each binary message = u16 header length + JSON header + JPEG bytes. Header:
 *    {"seq", "cap" (capture time, glasses clock ms), "off" (estimated server − glasses clock ms),
 *     "w", "h", "rot" (sensor orientation; the viewer rotates), "enc" (ms to encode)}.
 *  - Clock offset: every 2 s a text {"type":"ping","t0":…}; the server replies {"type":"pong","t0","ts"}.
 *    The server can ack frames with {"type":"ack","seq","ts"}; then capture→server latency is logged here too.
 *
 * Plain RFC 6455 client (no library): handshake, masked client frames, reads text replies.
 */
final class CameraStream {
    private static final String TAG = "WornStream";
    private static final long FRAME_MS = 62;          // ~15 fps cap (preview runs at 15–30)
    private static final int QUALITY = 50;

    private volatile String url;
    private volatile boolean running;
    private Thread sender, encoder;
    private final Object encLock = new Object();
    private volatile boolean encoderBusy;
    private Raw pendingRaw;                            // camera → encoder (one slot)
    private final AtomicReference<Frame> mailbox = new AtomicReference<>();   // encoder → sender (one slot)
    private long lastGrab;
    private int seq;
    private volatile int rot;
    private volatile long offsetMs;                    // server_ms - glasses_ms
    private volatile boolean haveOffset;

    // stats (logged once a second)
    private int sent, dropped, grabbed;
    private long encSum, sendSum, bytes, ackLatSum, ackN, lastStats;
    private final long[] sentAt = new long[256];
    private final long[] capAt = new long[256];

    private static final class Raw { byte[] nv21; int w, h; long cap; }
    private static final class Frame { byte[] jpeg; int seq, w, h; long cap; int enc; }

    void setRotation(int r) { rot = r; }

    /** Backend base (http://host:port) for the clock offset when the server doesn't answer WS pings (A's /ws/camera). */
    private volatile String httpBase;
    void setHttpBase(String b) { httpBase = b; }

    /** A's /ws/camera wants: text {ts (server epoch ms), seq, w, h} then the JPEG as its own binary message. */
    private boolean plainMode() { String u = url; return u != null && u.contains("/ws/camera"); }

    private long lastHttpSync;
    /** Cristian's algorithm against GET /live/state?since=… (returns the server's ts cheaply). */
    private void httpClockSync() {
        String b = httpBase;
        long now = System.currentTimeMillis();
        if (b == null || now - lastHttpSync < 10000) return;
        lastHttpSync = now;
        try {
            java.net.HttpURLConnection c = (java.net.HttpURLConnection) new java.net.URL(b + "/live/state?since=999999999").openConnection();
            c.setConnectTimeout(1500); c.setReadTimeout(1500);
            long t0 = System.currentTimeMillis();
            java.io.InputStream in = c.getInputStream();
            byte[] buf = new byte[4096]; int n, tot = 0; ByteArrayOutputStream o = new ByteArrayOutputStream();
            while ((n = in.read(buf)) > 0 && tot < 65536) { o.write(buf, 0, n); tot += n; }
            long t1 = System.currentTimeMillis();
            c.disconnect();
            double ts = new JSONObject(o.toString("UTF-8")).getDouble("ts");
            long est = (long) (ts * 1000) - (t0 + t1) / 2;
            offsetMs = haveOffset ? (offsetMs * 3 + est) / 4 : est;
            haveOffset = true;
        } catch (Exception e) {
            Log.d(TAG, "clock sync: " + e.getMessage());
        }
    }

    synchronized void start(String wsUrl) {
        if (running && wsUrl.equals(url)) return;
        stop();
        url = wsUrl;
        running = true;
        encoder = new Thread(this::encodeLoop, "worn-stream-enc");
        sender = new Thread(this::sendLoop, "worn-stream-ws");
        encoder.start();
        sender.start();
        Log.i(TAG, "streaming to " + wsUrl);
    }

    synchronized void stop() {
        running = false;
        if (sender != null) sender.interrupt();
        if (encoder != null) encoder.interrupt();
        synchronized (encLock) { encLock.notifyAll(); }
        sender = encoder = null;
    }

    boolean isRunning() { return running; }

    /** Camera thread: copy this preview frame only if it's time and the encoder is free. Cheap otherwise. */
    void offer(Image img) {
        if (!running) return;
        long now = SystemClock.elapsedRealtime();
        if (now - lastGrab < FRAME_MS) return;
        if (encoderBusy) { dropped++; return; }
        lastGrab = now;
        Raw r = new Raw();
        r.w = img.getWidth(); r.h = img.getHeight();
        r.cap = System.currentTimeMillis();
        r.nv21 = toNv21(img);
        grabbed++;
        synchronized (encLock) { pendingRaw = r; encoderBusy = true; encLock.notifyAll(); }
    }

    private void encodeLoop() {
        ByteArrayOutputStream out = new ByteArrayOutputStream(48 * 1024);
        while (running) {
            Raw r;
            synchronized (encLock) {
                while (running && pendingRaw == null) { try { encLock.wait(); } catch (InterruptedException e) { return; } }
                r = pendingRaw; pendingRaw = null;
            }
            if (r == null) continue;
            long t0 = SystemClock.elapsedRealtime();
            out.reset();
            new YuvImage(r.nv21, ImageFormat.NV21, r.w, r.h, null).compressToJpeg(new Rect(0, 0, r.w, r.h), QUALITY, out);
            Frame f = new Frame();
            f.jpeg = out.toByteArray(); f.w = r.w; f.h = r.h; f.cap = r.cap; f.seq = ++seq;
            f.enc = (int) (SystemClock.elapsedRealtime() - t0);
            encoderBusy = false;
            if (mailbox.getAndSet(f) != null) dropped++;      // the socket was behind: replace, never queue
            synchronized (mailbox) { mailbox.notifyAll(); }
        }
    }

    // ------------------------------------------------------------------ WebSocket

    private void sendLoop() {
        while (running) {
            Socket sock = null;
            try {
                URI u = URI.create(url);
                int port = u.getPort() > 0 ? u.getPort() : 80;
                sock = new Socket();
                sock.setTcpNoDelay(true);
                sock.setSendBufferSize(64 * 1024);   // small: a slow link shows up as backpressure, not hidden buffering
                sock.connect(new InetSocketAddress(u.getHost(), port), 3000);
                OutputStream os = sock.getOutputStream();
                InputStream is = sock.getInputStream();
                handshake(os, is, u.getHost() + ":" + port, (u.getRawPath() == null || u.getRawPath().isEmpty() ? "/" : u.getRawPath())
                        + (u.getRawQuery() != null ? "?" + u.getRawQuery() : ""));
                Log.i(TAG, "connected " + url);
                final Socket s = sock;
                Thread reader = new Thread(() -> readLoop(s, is), "worn-stream-rd");
                reader.start();
                long lastPing = 0;
                while (running && !sock.isClosed()) {
                    long now = System.currentTimeMillis();
                    if (plainMode()) httpClockSync();
                    else if (now - lastPing > 2000) { lastPing = now; sendFrame(os, 0x1, ("{\"type\":\"ping\",\"t0\":" + now + "}").getBytes(StandardCharsets.UTF_8)); }
                    Frame f = mailbox.getAndSet(null);
                    if (f == null) { synchronized (mailbox) { mailbox.wait(200); } continue; }
                    JSONObject h = new JSONObject();
                    h.put("seq", f.seq).put("cap", f.cap).put("off", haveOffset ? offsetMs : JSONObject.NULL)
                            .put("w", f.w).put("h", f.h).put("rot", rot).put("enc", f.enc);
                    byte[] hb = h.toString().getBytes(StandardCharsets.UTF_8);
                    byte[] msg = new byte[2 + hb.length + f.jpeg.length];
                    msg[0] = (byte) (hb.length >> 8); msg[1] = (byte) hb.length;
                    System.arraycopy(hb, 0, msg, 2, hb.length);
                    System.arraycopy(f.jpeg, 0, msg, 2 + hb.length, f.jpeg.length);
                    long t0 = SystemClock.elapsedRealtime();
                    if (plainMode()) {
                        JSONObject m = new JSONObject();
                        m.put("ts", f.cap + (haveOffset ? offsetMs : 0)).put("seq", f.seq).put("w", f.w).put("h", f.h).put("rot", rot);
                        sendFrame(os, 0x1, m.toString().getBytes(StandardCharsets.UTF_8));
                        sendFrame(os, 0x2, f.jpeg);                   // blocks while the socket is behind
                    } else sendFrame(os, 0x2, msg);
                    long ms = SystemClock.elapsedRealtime() - t0;
                    sentAt[f.seq & 255] = System.currentTimeMillis();
                    capAt[f.seq & 255] = f.cap;
                    sent++; encSum += f.enc; sendSum += ms; bytes += f.jpeg.length;
                    stats();
                }
            } catch (InterruptedException e) {
                break;
            } catch (Exception e) {
                Log.w(TAG, "stream: " + e.getMessage());
            } finally {
                if (sock != null) try { sock.close(); } catch (Exception ignored) { }
            }
            if (running) try { Thread.sleep(1500); } catch (InterruptedException e) { break; }   // reconnect
        }
        Log.i(TAG, "stream stopped");
    }

    private void stats() {
        long now = System.currentTimeMillis();
        if (now - lastStats < 1000 || sent == 0) return;
        float secs = (now - lastStats) / 1000f;
        lastStats = now;
        String ack = ackN > 0 ? " capture→server " + (ackLatSum / ackN) + "ms" : " (no acks)";
        Log.i(TAG, String.format(java.util.Locale.US, "%.1f fps sent, %d dropped, %d grabbed, enc %dms, send %dms, %d KB/frame,%s, clock off %s",
                sent / secs, dropped, grabbed, encSum / sent, sendSum / sent, bytes / sent / 1024, ack, haveOffset ? offsetMs + "ms" : "?"));
        sent = dropped = grabbed = 0; encSum = sendSum = bytes = 0; ackLatSum = ackN = 0;
    }

    private void readLoop(Socket s, InputStream is) {
        try {
            while (running && !s.isClosed()) {
                int b0 = is.read(); if (b0 < 0) break;
                int b1 = is.read(); if (b1 < 0) break;
                long len = b1 & 0x7f;
                if (len == 126) len = (is.read() << 8) | is.read();
                else if (len == 127) { len = 0; for (int i = 0; i < 8; i++) len = (len << 8) | is.read(); }
                byte[] p = new byte[(int) len];
                int got = 0; while (got < len) { int n = is.read(p, got, (int) len - got); if (n < 0) return; got += n; }
                int op = b0 & 0x0f;
                if (op == 0x8) break;
                if (op != 0x1) continue;
                JSONObject j = new JSONObject(new String(p, StandardCharsets.UTF_8));
                long now = System.currentTimeMillis();
                if ("pong".equals(j.optString("type"))) {
                    long t0 = j.getLong("t0"), ts = j.getLong("ts");
                    long est = ts - (t0 + now) / 2;                // Cristian: server − glasses
                    offsetMs = haveOffset ? (offsetMs * 3 + est) / 4 : est;
                    haveOffset = true;
                } else if ("ack".equals(j.optString("type")) && haveOffset) {
                    int sq = j.getInt("seq");
                    long cap = capAt[sq & 255];
                    if (cap > 0) { ackLatSum += j.getLong("ts") - offsetMs - cap; ackN++; }
                }
            }
        } catch (Exception e) {
            Log.d(TAG, "reader: " + e.getMessage());
        } finally {
            try { s.close(); } catch (Exception ignored) { }
        }
    }

    private static void handshake(OutputStream os, InputStream is, String host, String path) throws Exception {
        byte[] nonce = new byte[16];
        new SecureRandom().nextBytes(nonce);
        String key = Base64.encodeToString(nonce, Base64.NO_WRAP);
        String req = "GET " + path + " HTTP/1.1\r\nHost: " + host + "\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                + "Sec-WebSocket-Key: " + key + "\r\nSec-WebSocket-Version: 13\r\n\r\n";
        os.write(req.getBytes(StandardCharsets.US_ASCII));
        os.flush();
        StringBuilder resp = new StringBuilder();
        int c, nl = 0;
        while ((c = is.read()) >= 0) {
            resp.append((char) c);
            if (c == '\n') { if (++nl >= 1 && resp.toString().endsWith("\r\n\r\n")) break; }
            if (resp.length() > 4096) break;
        }
        if (!resp.toString().startsWith("HTTP/1.1 101")) throw new Exception("handshake: " + resp.toString().split("\r\n")[0]);
    }

    private final byte[] mask = new byte[4];
    private final SecureRandom rnd = new SecureRandom();

    private void sendFrame(OutputStream os, int opcode, byte[] payload) throws Exception {
        rnd.nextBytes(mask);
        int len = payload.length;
        byte[] head = len < 126 ? new byte[6] : len < 65536 ? new byte[8] : new byte[14];
        head[0] = (byte) (0x80 | opcode);
        int i;
        if (len < 126) { head[1] = (byte) (0x80 | len); i = 2; }
        else if (len < 65536) { head[1] = (byte) (0x80 | 126); head[2] = (byte) (len >> 8); head[3] = (byte) len; i = 4; }
        else { head[1] = (byte) (0x80 | 127); for (int k = 0; k < 8; k++) head[2 + k] = (byte) (k < 4 ? 0 : (len >> (8 * (7 - k)))); i = 10; }
        System.arraycopy(mask, 0, head, i, 4);
        byte[] body = new byte[len];
        for (int k = 0; k < len; k++) body[k] = (byte) (payload[k] ^ mask[k & 3]);
        os.write(head);
        os.write(body);
        os.flush();
    }

    /** YUV_420_888 → NV21 (Y plane, then interleaved V/U), honouring row and pixel strides. */
    private static byte[] toNv21(Image img) {
        int w = img.getWidth(), h = img.getHeight();
        byte[] out = new byte[w * h * 3 / 2];
        Image.Plane[] p = img.getPlanes();
        ByteBuffer y = p[0].getBuffer();
        int yRow = p[0].getRowStride();
        if (yRow == w) { y.position(0); y.get(out, 0, w * h); }
        else for (int r = 0; r < h; r++) { y.position(r * yRow); y.get(out, r * w, w); }
        ByteBuffer u = p[1].getBuffer(), v = p[2].getBuffer();
        int cRow = p[1].getRowStride(), cPix = p[1].getPixelStride();
        int o = w * h;
        for (int r = 0; r < h / 2; r++) {
            int base = r * cRow;
            for (int c = 0; c < w / 2; c++) {
                int idx = base + c * cPix;
                out[o++] = v.get(idx);
                out[o++] = u.get(idx);
            }
        }
        return out;
    }
}
