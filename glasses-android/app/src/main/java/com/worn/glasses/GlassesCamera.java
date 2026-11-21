package com.worn.glasses;

import android.annotation.SuppressLint;
import android.content.Context;
import android.graphics.ImageFormat;
import android.hardware.camera2.CameraAccessException;
import android.hardware.camera2.CameraCaptureSession;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraDevice;
import android.hardware.camera2.CameraManager;
import android.hardware.camera2.CameraMetadata;
import android.hardware.camera2.CaptureRequest;
import android.hardware.camera2.params.StreamConfigurationMap;
import android.media.Image;
import android.media.ImageReader;
import android.os.Handler;
import android.os.HandlerThread;
import android.util.Log;
import android.util.Size;
import android.view.Surface;

import java.nio.ByteBuffer;
import java.util.Arrays;

/**
 * Plain Camera2 still capture (the glasses-side MicroLumin camera SDK is not in the kit).
 *
 * The camera stays open while the app is in front, streaming small YUV frames that we drop
 * so auto-exposure and focus have settled by the time the button is pressed. If opening fails
 * (another app holds the camera, or it was disconnected), takePicture() reopens it and waits
 * a short warm-up before the still.
 */
final class GlassesCamera {
    interface Callback {
        void onJpeg(byte[] jpeg);
        void onError(String message);
    }

    private static final String TAG = "WornCam";
    private static final int MAX_LONG_EDGE = 1920; // backend shrinks to 1024 anyway; keep the upload small
    private static final long WARMUP_MS = 700;      // AE/AF settle time after a cold open

    private final CameraManager manager;
    private final HandlerThread thread = new HandlerThread("worn-camera");
    private final Handler handler;

    private CameraDevice device;
    private CameraCaptureSession session;
    private ImageReader reader;
    private ImageReader previewReader; // frames are discarded; it only keeps AE/AF running
    private Surface previewSurface;
    private String cameraId;
    private int sensorOrientation;
    private long readySince;
    private boolean opening;
    private Callback pending; // one capture at a time
    private volatile CameraStream stream;
    void setStream(CameraStream s) { stream = s; if (s != null) s.setRotation(sensorOrientation); }
    private CaptureRequest.Builder previewReq;

    /** 64×64 grayscale thumbnails from the preview stream, for the on-device ink check. */
    interface LumaListener { void onLuma(byte[] gray64); }
    private volatile LumaListener luma;
    private long lastLuma;
    static final int THUMB = 64;
    void setLumaListener(LumaListener l) { luma = l; }

    /** Centre square of the Y plane, box-sampled to 64×64, at most ~3 per second. */
    private void feedLuma(Image f) {
        LumaListener l = luma;
        if (l == null) return;
        long now = System.currentTimeMillis();
        if (now - lastLuma < 330) return;
        lastLuma = now;
        Image.Plane y = f.getPlanes()[0];
        java.nio.ByteBuffer buf = y.getBuffer();
        int rs = y.getRowStride(), ps = y.getPixelStride();
        int w = f.getWidth(), h = f.getHeight();
        int side = Math.min(w, h);                 // centre square: where the page is when you look down at it
        int x0 = (w - side) / 2, y0 = (h - side) / 2;
        int step = side / THUMB;
        byte[] out = new byte[THUMB * THUMB];
        for (int ty = 0; ty < THUMB; ty++) {
            for (int tx = 0; tx < THUMB; tx++) {
                int sum = 0, n = 0;
                int sy = y0 + ty * step, sx = x0 + tx * step;
                for (int dy = 0; dy < step; dy += 2) {
                    int row = (sy + dy) * rs;
                    for (int dx = 0; dx < step; dx += 2) { sum += buf.get(row + (sx + dx) * ps) & 0xff; n++; }
                }
                out[ty * THUMB + tx] = (byte) (n == 0 ? 0 : sum / n);
            }
        }
        l.onLuma(out);
    }

    GlassesCamera(Context ctx) {
        manager = (CameraManager) ctx.getSystemService(Context.CAMERA_SERVICE);
        thread.start();
        handler = new Handler(thread.getLooper());
    }

    String describe() {
        if (session != null) return "camera " + cameraId + " ready";
        if (opening) return "camera opening";
        return "camera closed";
    }

    void open() { handler.post(this::openInternal); }

    void close() { handler.post(this::closeInternal); }

    void release() {
        handler.post(() -> { closeInternal(); thread.quitSafely(); });
    }

    void takePicture(Callback cb) {
        handler.post(() -> {
            if (pending != null) { cb.onError("Still checking the last photo"); return; }
            pending = cb;
            if (session == null) {
                openInternal(); // capture fires from onConfigured once ready
                return;
            }
            long wait = Math.max(0, WARMUP_MS - (System.currentTimeMillis() - readySince));
            handler.postDelayed(this::captureInternal, wait);
        });
    }

    // ------------------------------------------------------------------ internals (camera thread)

    @SuppressLint("MissingPermission") // granted at install with `adb install -g`; checked in MainActivity
    private void openInternal() {
        if (device != null || opening) return;
        try {
            cameraId = pickCamera();
            if (cameraId == null) { fail("No camera found"); return; }
            CameraCharacteristics cc = manager.getCameraCharacteristics(cameraId);
            Integer so = cc.get(CameraCharacteristics.SENSOR_ORIENTATION);
            sensorOrientation = so == null ? 0 : so;
            Size size = pickJpegSize(cc);
            Log.i(TAG, "opening camera " + cameraId + " jpeg " + size + " sensorOrientation " + sensorOrientation);
            if (stream != null) stream.setRotation(sensorOrientation);
            reader = ImageReader.newInstance(size.getWidth(), size.getHeight(), ImageFormat.JPEG, 2);
            reader.setOnImageAvailableListener(this::onImage, handler);
            Size ps = pickPreviewSize(cc);
            previewReader = ImageReader.newInstance(ps.getWidth(), ps.getHeight(), ImageFormat.YUV_420_888, 2);
            previewReader.setOnImageAvailableListener(pr -> {
                Image f = pr.acquireLatestImage();
                if (f != null) {
                    try { feedLuma(f); } catch (Exception e) { Log.w(TAG, "luma", e); }
                    CameraStream st = stream;
                    if (st != null) { try { st.offer(f); } catch (Exception e) { Log.w(TAG, "stream", e); } }
                    f.close();
                }
            }, handler);
            previewSurface = previewReader.getSurface();
            opening = true;
            manager.openCamera(cameraId, new CameraDevice.StateCallback() {
                @Override public void onOpened(CameraDevice d) {
                    // A close() may have run while the camera was opening (fast pause/resume): don't use torn-down readers.
                    if (!opening || reader == null || previewSurface == null) {
                        Log.w(TAG, "camera opened after close; releasing it");
                        try { d.close(); } catch (Exception ignored) { }
                        return;
                    }
                    device = d;
                    startSession();
                }
                @Override public void onDisconnected(CameraDevice d) {
                    Log.w(TAG, "camera disconnected (another app took it?)");
                    d.close();
                    device = null;
                    closeInternal();
                    fail("Camera busy, press again");
                }
                @Override public void onError(CameraDevice d, int error) {
                    Log.e(TAG, "camera error " + error);
                    d.close();
                    device = null;
                    closeInternal();
                    fail("Camera error " + error + ", press again");
                }
            }, handler);
        } catch (CameraAccessException | SecurityException | IllegalArgumentException e) {
            Log.e(TAG, "open failed", e);
            closeInternal();
            fail("Can't open camera: " + e.getMessage());
        }
    }

    private void startSession() {
        if (device == null || reader == null || previewSurface == null) { closeInternal(); return; }
        try {
            device.createCaptureSession(Arrays.asList(previewSurface, reader.getSurface()),
                    new CameraCaptureSession.StateCallback() {
                        @Override public void onConfigured(CameraCaptureSession s) {
                            if (device == null) { try { s.close(); } catch (Exception ignored) { } return; }
                            session = s;
                            opening = false;
                            readySince = System.currentTimeMillis();
                            try {
                                CaptureRequest.Builder b = device.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW);
                                b.addTarget(previewSurface);
                                b.set(CaptureRequest.CONTROL_MODE, CameraMetadata.CONTROL_MODE_AUTO);
                                b.set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_PICTURE);
                                b.set(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE, new android.util.Range<>(15, 30));
                                previewReq = b;
                                s.setRepeatingRequest(b.build(), null, handler);
                                // Let AE/AWB/AF settle once, then lock them: no hunting per frame.
                                handler.postDelayed(GlassesCamera.this::lock3A, 1500);
                            } catch (CameraAccessException | IllegalStateException e) {
                                Log.w(TAG, "preview request failed", e);
                            }
                            Log.i(TAG, "camera ready");
                            if (pending != null) handler.postDelayed(GlassesCamera.this::captureInternal, WARMUP_MS);
                        }
                        @Override public void onConfigureFailed(CameraCaptureSession s) {
                            Log.e(TAG, "session configure failed");
                            closeInternal();
                            fail("Camera setup failed, press again");
                        }
                    }, handler);
        } catch (CameraAccessException | IllegalStateException e) {
            Log.e(TAG, "createCaptureSession failed", e);
            closeInternal();
            fail("Camera setup failed, press again");
        }
    }

    private void lock3A() {
        if (session == null || previewReq == null) return;
        try {
            previewReq.set(CaptureRequest.CONTROL_AE_LOCK, true);
            previewReq.set(CaptureRequest.CONTROL_AWB_LOCK, true);
            previewReq.set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_AUTO);
            previewReq.set(CaptureRequest.CONTROL_AF_TRIGGER, CameraMetadata.CONTROL_AF_TRIGGER_START);
            session.capture(previewReq.build(), null, handler);        // one AF sweep, then hold
            previewReq.set(CaptureRequest.CONTROL_AF_TRIGGER, CameraMetadata.CONTROL_AF_TRIGGER_IDLE);
            session.setRepeatingRequest(previewReq.build(), null, handler);
            Log.i(TAG, "AE/AWB/AF locked");
        } catch (CameraAccessException | IllegalStateException e) {
            Log.w(TAG, "3A lock failed", e);
        }
    }

    private void captureInternal() {
        if (pending == null) return;
        if (session == null || device == null) { fail("Camera not ready, press again"); return; }
        try {
            CaptureRequest.Builder b = device.createCaptureRequest(CameraDevice.TEMPLATE_STILL_CAPTURE);
            b.addTarget(reader.getSurface());
            b.set(CaptureRequest.CONTROL_MODE, CameraMetadata.CONTROL_MODE_AUTO);
            b.set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_PICTURE);
            b.set(CaptureRequest.JPEG_QUALITY, (byte) 90);
            // Glasses don't rotate relative to the head, so the sensor orientation is the whole story.
            // The backend applies the EXIF orientation (ImageOps.exif_transpose).
            b.set(CaptureRequest.JPEG_ORIENTATION, sensorOrientation);
            session.capture(b.build(), null, handler);
        } catch (CameraAccessException | IllegalStateException e) {
            Log.e(TAG, "capture failed", e);
            closeInternal();
            fail("Photo failed, press again");
        }
    }

    private void onImage(ImageReader r) {
        Image img = r.acquireLatestImage();
        if (img == null) return;
        try {
            ByteBuffer buf = img.getPlanes()[0].getBuffer();
            byte[] jpeg = new byte[buf.remaining()];
            buf.get(jpeg);
            Callback cb = pending;
            pending = null;
            Log.i(TAG, "jpeg " + jpeg.length + " bytes");
            if (cb != null) cb.onJpeg(jpeg);
        } finally {
            img.close();
        }
    }

    private void fail(String msg) {
        opening = false;
        Callback cb = pending;
        pending = null;
        if (cb != null) cb.onError(msg);
    }

    private void closeInternal() {
        opening = false;
        if (session != null) { try { session.close(); } catch (Exception ignored) {} session = null; }
        if (device != null) { try { device.close(); } catch (Exception ignored) {} device = null; }
        if (reader != null) { reader.close(); reader = null; }
        previewSurface = null;
        previewReq = null;
        if (previewReader != null) { previewReader.close(); previewReader = null; }
    }

    private String pickCamera() throws CameraAccessException {
        String[] ids = manager.getCameraIdList();
        for (String id : ids) {
            Integer facing = manager.getCameraCharacteristics(id).get(CameraCharacteristics.LENS_FACING);
            if (facing != null && facing == CameraCharacteristics.LENS_FACING_BACK) return id;
        }
        return ids.length > 0 ? ids[0] : null; // the M6 has one world-facing camera
    }

    private static Size pickPreviewSize(CameraCharacteristics cc) {
        StreamConfigurationMap map = cc.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP);
        Size[] sizes = map == null ? null : map.getOutputSizes(ImageFormat.YUV_420_888);
        if (sizes == null || sizes.length == 0) return new Size(640, 480);
        for (Size s : sizes) if (s.getWidth() == 640 && s.getHeight() == 480) return s;   // stream size
        for (Size s : sizes) if (s.getWidth() == 480 && s.getHeight() == 360) return s;
        Size best = null;
        for (Size s : sizes) {
            if (s.getWidth() < 320) continue;
            if (best == null || (long) s.getWidth() * s.getHeight() < (long) best.getWidth() * best.getHeight()) best = s;
        }
        return best != null ? best : sizes[0];
    }

    private static Size pickJpegSize(CameraCharacteristics cc) {
        StreamConfigurationMap map = cc.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP);
        Size[] sizes = map == null ? null : map.getOutputSizes(ImageFormat.JPEG);
        if (sizes == null || sizes.length == 0) return new Size(1280, 960);
        Size best = null, smallest = sizes[0];
        for (Size s : sizes) {
            long area = (long) s.getWidth() * s.getHeight();
            if (area < (long) smallest.getWidth() * smallest.getHeight()) smallest = s;
            if (Math.max(s.getWidth(), s.getHeight()) > MAX_LONG_EDGE) continue;
            if (best == null || area > (long) best.getWidth() * best.getHeight()) best = s;
        }
        return best != null ? best : smallest;
    }
}
