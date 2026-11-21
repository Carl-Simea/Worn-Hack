package com.worn.glasses;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/** Blocking HTTP calls to the Worn backend (agent A). Call off the UI thread. */
final class Backend {
    private final String api;

    Backend(String api) { this.api = api.replaceAll("/+$", ""); }

    /** GET /session, or null when the phone hasn't started one yet (404). */
    JSONObject session() throws IOException {
        HttpURLConnection c = open("/session");
        c.setConnectTimeout(3000);
        c.setReadTimeout(3000);
        try {
            int code = c.getResponseCode();
            if (code == 404) return null;
            String body = read(code < 400 ? c.getInputStream() : c.getErrorStream());
            if (code >= 400) throw new IOException("GET /session " + code + ": " + body);
            return new JSONObject(body);
        } catch (org.json.JSONException e) {
            throw new IOException("bad /session json", e);
        } finally {
            c.disconnect();
        }
    }

    /**
     * POST /grade as multipart {image, char, lang}. char/lang may be null; the backend then uses
     * the active session. Returns the raw JSON body: {correct, score, feedback, seen, char, lang, ts, latency_ms}.
     */
    String grade(byte[] jpeg, String ch, String lang) throws IOException {
        String boundary = "----worn" + System.nanoTime();
        HttpURLConnection c = open("/grade");
        c.setConnectTimeout(5000);
        c.setReadTimeout(60000); // backend grader timeout is 45s
        c.setDoOutput(true);
        c.setRequestMethod("POST");
        c.setRequestProperty("Content-Type", "multipart/form-data; boundary=" + boundary);

        ByteArrayOutputStream body = new ByteArrayOutputStream(jpeg.length + 1024);
        if (ch != null) field(body, boundary, "char", ch);
        if (lang != null) field(body, boundary, "lang", lang);
        ascii(body, "--" + boundary + "\r\n"
                + "Content-Disposition: form-data; name=\"image\"; filename=\"glasses.jpg\"\r\n"
                + "Content-Type: image/jpeg\r\n\r\n");
        body.write(jpeg);
        ascii(body, "\r\n--" + boundary + "--\r\n");

        c.setFixedLengthStreamingMode(body.size());
        try {
            try (OutputStream out = c.getOutputStream()) { body.writeTo(out); }
            int code = c.getResponseCode();
            String resp = read(code < 400 ? c.getInputStream() : c.getErrorStream());
            if (code >= 400) throw new HttpError(code, resp);
            return resp;
        } finally {
            c.disconnect();
        }
    }

    static final class HttpError extends IOException {
        final int code;
        HttpError(int code, String body) { super("HTTP " + code + ": " + body); this.code = code; }
    }

    /** POST /stroke-match multipart {image, stroke_index, char?, lang?} (tier 2, OpenCV, < 300 ms server-side). */
    String strokeMatch(byte[] jpeg, int strokeIndex, String ch, String lang) throws IOException {
        String boundary = "----worns" + System.nanoTime();
        HttpURLConnection c = open("/stroke-match");
        c.setConnectTimeout(3000);
        c.setReadTimeout(8000);
        c.setDoOutput(true);
        c.setRequestMethod("POST");
        c.setRequestProperty("Content-Type", "multipart/form-data; boundary=" + boundary);
        ByteArrayOutputStream body = new ByteArrayOutputStream(jpeg.length + 512);
        field(body, boundary, "stroke_index", String.valueOf(strokeIndex));
        if (ch != null && !ch.isEmpty()) field(body, boundary, "char", ch);
        if (lang != null && !lang.isEmpty()) field(body, boundary, "lang", lang);
        ascii(body, "--" + boundary + "\r\n"
                + "Content-Disposition: form-data; name=\"image\"; filename=\"stroke.jpg\"\r\n"
                + "Content-Type: image/jpeg\r\n\r\n");
        body.write(jpeg);
        ascii(body, "\r\n--" + boundary + "--\r\n");
        c.setFixedLengthStreamingMode(body.size());
        try {
            try (OutputStream out = c.getOutputStream()) { body.writeTo(out); }
            int code = c.getResponseCode();
            String resp = read(code < 400 ? c.getInputStream() : c.getErrorStream());
            if (code >= 400) throw new HttpError(code, resp);
            return resp;
        } finally {
            c.disconnect();
        }
    }

    /** POST /voice multipart {audio (16 kHz mono WAV), screen}. Returns the raw JSON reply
     *  {heard, intent, args, say, say_url, nav, hint, session?}. */
    String voice(byte[] wav, String screen) throws IOException {
        String boundary = "----wornv" + System.nanoTime();
        HttpURLConnection c = open("/voice");
        c.setConnectTimeout(3000);
        c.setReadTimeout(30000);
        c.setDoOutput(true);
        c.setRequestMethod("POST");
        c.setRequestProperty("Content-Type", "multipart/form-data; boundary=" + boundary);
        ByteArrayOutputStream body = new ByteArrayOutputStream(wav.length + 512);
        if (screen != null) field(body, boundary, "screen", screen);
        ascii(body, "--" + boundary + "\r\n"
                + "Content-Disposition: form-data; name=\"audio\"; filename=\"voice.wav\"\r\n"
                + "Content-Type: audio/wav\r\n\r\n");
        body.write(wav);
        ascii(body, "\r\n--" + boundary + "--\r\n");
        c.setFixedLengthStreamingMode(body.size());
        try {
            try (OutputStream out = c.getOutputStream()) { body.writeTo(out); }
            int code = c.getResponseCode();
            String resp = read(code < 400 ? c.getInputStream() : c.getErrorStream());
            if (code >= 400) throw new HttpError(code, resp);
            return resp;
        } finally {
            c.disconnect();
        }
    }

    /** POST /event {type, data}. Short timeouts: used for the heartbeat. */
    void event(String type, JSONObject data) throws IOException {
        HttpURLConnection c = open("/event");
        c.setConnectTimeout(2500);
        c.setReadTimeout(2500);
        c.setDoOutput(true);
        c.setRequestMethod("POST");
        c.setRequestProperty("Content-Type", "application/json");
        String body;
        try {
            body = new JSONObject().put("type", type).put("data", data == null ? new JSONObject() : data).toString();
        } catch (org.json.JSONException e) { throw new IOException(e); }
        try (java.io.OutputStream os = c.getOutputStream()) { os.write(body.getBytes(StandardCharsets.UTF_8)); }
        int code = c.getResponseCode();
        read(code < 400 ? c.getInputStream() : c.getErrorStream());
        if (code >= 400) throw new HttpError(code, "POST /event");
    }

    /** GET /health answers 200 within ~1.5 s. */
    boolean reachable() {
        try {
            HttpURLConnection c = open("/health");
            c.setConnectTimeout(1500);
            c.setReadTimeout(1500);
            int code = c.getResponseCode();
            read(code < 400 ? c.getInputStream() : c.getErrorStream());
            return code == 200;
        } catch (IOException e) {
            return false;
        }
    }

    private HttpURLConnection open(String path) throws IOException {
        HttpURLConnection c = (HttpURLConnection) new URL(api + path).openConnection();
        c.setUseCaches(false);
        return c;
    }

    private static void field(ByteArrayOutputStream b, String boundary, String name, String value) throws IOException {
        ascii(b, "--" + boundary + "\r\nContent-Disposition: form-data; name=\"" + name + "\"\r\n"
                + "Content-Type: text/plain; charset=utf-8\r\n\r\n");
        b.write(value.getBytes(StandardCharsets.UTF_8));
        ascii(b, "\r\n");
    }

    private static void ascii(ByteArrayOutputStream b, String s) throws IOException {
        b.write(s.getBytes(StandardCharsets.UTF_8));
    }

    private static String read(InputStream in) throws IOException {
        if (in == null) return "";
        try (InputStream is = in) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            int n;
            while ((n = is.read(buf)) > 0) out.write(buf, 0, n);
            return out.toString("UTF-8");
        }
    }
}
