"""Stand-in for the glasses camera stream, to test /live's live camera panel without hardware (owner: agent B).

Serves synthetic frames (paper, a box, a pen writing a character stroke by stroke) as
  GET /ws/camera   WebSocket: a JSON text {"ts": <epoch s>, "seq": n} then one binary JPEG, per frame
  GET /camera.mjpg multipart/x-mixed-replace JPEG
  GET /openapi.json lists both, the way FastAPI would

  uv run --with pillow python web/dev/cam_sim.py --port 8097 [--fps 15] [--char 你]
  then open /live?cam=http://127.0.0.1:8097   (or point a backend at it)
"""
import argparse, base64, hashlib, io, json, math, socket, struct, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image, ImageDraw, ImageFont

FONT = "/System/Library/Fonts/STHeiti Medium.ttc"


class Frames:
    def __init__(self, ch, fps):
        self.ch, self.fps, self.seq, self.jpeg, self.ts = ch, fps, 0, b"", 0.0
        self.cond = threading.Condition()
        try:
            self.font = ImageFont.truetype(FONT, 300)
        except OSError:
            self.font = ImageFont.load_default()
        threading.Thread(target=self.run, daemon=True).start()

    def render(self, t):
        im = Image.new("RGB", (640, 480), (236, 230, 216))
        d = ImageDraw.Draw(im)
        d.rectangle((170, 90, 470, 390), outline=(205, 190, 165), width=3)
        # the character "appears" left to right over 6 s, then holds for 2 s, then repeats
        k = (t % 8) / 6
        glyph = Image.new("L", (640, 480), 0)
        ImageDraw.Draw(glyph).text((320, 240), self.ch, font=self.font, fill=255, anchor="mm")
        mask = Image.new("L", (640, 480), 0)
        ImageDraw.Draw(mask).rectangle((0, 0, int(170 + 300 * min(1, k)), 480), fill=255)
        im.paste((28, 30, 40), (0, 0), Image.composite(glyph, mask, mask))
        if k < 1:  # the pen
            px, py = 170 + 300 * k, 240 + 90 * math.sin(t * 5)
            d.line((px, py, px + 120, py + 160), fill=(70, 60, 55), width=14)
            d.ellipse((px - 6, py - 6, px + 6, py + 6), fill=(20, 20, 30))
        d.text((12, 10), time.strftime("%H:%M:%S"), fill=(120, 110, 95))
        out = io.BytesIO()
        im.rotate(math.sin(t * .7) * 1.5, fillcolor=(120, 110, 95)).save(out, "JPEG", quality=75)
        return out.getvalue()

    def run(self):
        t0 = time.time()
        while True:
            t = time.time()
            j = self.render(t - t0)
            with self.cond:
                self.jpeg, self.ts, self.seq = j, t, self.seq + 1
                self.cond.notify_all()
            time.sleep(max(0, 1 / self.fps - (time.time() - t)))

    def next(self, seen):
        with self.cond:
            self.cond.wait_for(lambda: self.seq != seen, timeout=2)
            return self.seq, self.ts, self.jpeg


def ws_frame(payload: bytes, opcode: int) -> bytes:
    n = len(payload)
    head = bytes([0x80 | opcode])
    if n < 126:
        head += bytes([n])
    elif n < 65536:
        head += bytes([126]) + struct.pack(">H", n)
    else:
        head += bytes([127]) + struct.pack(">Q", n)
    return head + payload


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/openapi.json":
            body = json.dumps({"openapi": "3.1.0", "paths": {"/camera.mjpg": {}, "/ws/camera": {}}}).encode()
            self.send_response(200)
            for k, v in (("Content-Type", "application/json"), ("Content-Length", str(len(body))), ("Access-Control-Allow-Origin", "*")):
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/ws/camera" and self.headers.get("Upgrade", "").lower() == "websocket":
            key = self.headers["Sec-WebSocket-Key"]
            acc = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
            self.send_response(101)
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", acc)
            self.end_headers()
            seen = 0
            try:
                while True:
                    seen, ts, jpg = FR.next(seen)
                    self.wfile.write(ws_frame(json.dumps({"ts": ts, "seq": seen}).encode(), 0x1))
                    self.wfile.write(ws_frame(jpg, 0x2))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, socket.error):
                return
        if path == "/camera.mjpg":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            seen = 0
            try:
                while True:
                    seen, ts, jpg = FR.next(seen)
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, socket.error):
                return
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8097)
    ap.add_argument("--fps", type=float, default=15)
    ap.add_argument("--char", default="你")
    a = ap.parse_args()
    FR = Frames(a.char, a.fps)
    print(f"camera sim on http://127.0.0.1:{a.port}  (/ws/camera, /camera.mjpg)")
    ThreadingHTTPServer(("0.0.0.0", a.port), H).serve_forever()
