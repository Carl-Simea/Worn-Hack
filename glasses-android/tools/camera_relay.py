#!/usr/bin/env python3
"""Live camera relay for the glasses (agent D). Standard library only; Python 3.9+.

    python3 glasses-android/tools/camera_relay.py            # :8790
    adb reverse tcp:8790 tcp:8790                             # glasses → Mac over USB (run.sh does this)

Glasses → relay   WS  /glasses/camera/ws   binary: u16 header length + JSON header + JPEG
                                           header {seq, cap (glasses ms), off (server−glasses ms), w, h, rot, enc}
                                           text {"type":"ping","t0"} → we answer {"type":"pong","t0","ts"}
                                           every frame is acked {"type":"ack","seq","ts"} (latency on the glasses)
Relay → viewers   WS  /ws/camera           text {"ts","seq","lat_ms","rot","w","h"} then binary JPEG (B's /live format)
                  GET /camera.mjpg         multipart MJPEG, latest frame only
                  GET /camera.jpg          latest frame
                  GET /stats               JSON: fps, ingest latency (capture → relay, clock-corrected), sizes
                  GET /view                test page: shows the feed + capture → screen latency

Viewers always get the newest frame; a slow viewer skips frames, it never builds a queue.
"""
import asyncio
import base64
import hashlib
import json
import struct
import sys
import time

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8790
GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

latest = {"jpeg": None, "meta": None}
new_frame = asyncio.Event() if False else None   # set in main()
stats = {"frames": 0, "lat_sum": 0.0, "lat_n": 0, "bytes": 0, "t": time.time(), "fps": 0.0,
         "lat_ms": None, "kb": None, "viewers": 0, "glasses": 0, "enc_ms": None}


def now_ms():
    return time.time() * 1000.0


# ------------------------------------------------------------------ websocket helpers

async def ws_read(reader):
    """One message: (opcode, payload). Handles masking and the 16/64-bit lengths (no fragmentation needed)."""
    b0, b1 = await reader.readexactly(2)
    op, masked, ln = b0 & 0x0F, b1 & 0x80, b1 & 0x7F
    if ln == 126:
        ln = struct.unpack(">H", await reader.readexactly(2))[0]
    elif ln == 127:
        ln = struct.unpack(">Q", await reader.readexactly(8))[0]
    mask = await reader.readexactly(4) if masked else None
    data = await reader.readexactly(ln)
    if mask:
        data = bytes(b ^ mask[i & 3] for i, b in enumerate(data)) if ln < 4096 else _unmask(data, mask)
    return op, data


def _unmask(data, mask):
    """XOR with the repeating 4-byte mask, as one big integer (fast for JPEG-sized payloads)."""
    full = (mask * (len(data) // 4 + 1))[: len(data)]
    return (int.from_bytes(data, "big") ^ int.from_bytes(full, "big")).to_bytes(len(data), "big")


def ws_frame(op, payload):
    ln = len(payload)
    if ln < 126:
        head = struct.pack(">BB", 0x80 | op, ln)
    elif ln < 65536:
        head = struct.pack(">BBH", 0x80 | op, 126, ln)
    else:
        head = struct.pack(">BBQ", 0x80 | op, 127, ln)
    return head + payload


async def upgrade(writer, headers):
    key = headers.get("sec-websocket-key", "")
    acc = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
    writer.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                  f"Sec-WebSocket-Accept: {acc}\r\n\r\n").encode())
    await writer.drain()


# ------------------------------------------------------------------ handlers

async def ingest(reader, writer):
    stats["glasses"] += 1
    print("glasses connected", flush=True)
    try:
        while True:
            op, data = await ws_read(reader)
            t_recv = now_ms()
            if op == 0x8:
                break
            if op == 0x9:
                writer.write(ws_frame(0xA, data)); continue
            if op == 0x1:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    writer.write(ws_frame(0x1, json.dumps({"type": "pong", "t0": msg["t0"], "ts": int(t_recv)}).encode()))
                continue
            if op != 0x2 or len(data) < 2:
                continue
            hl = struct.unpack(">H", data[:2])[0]
            meta = json.loads(data[2:2 + hl])
            jpeg = data[2 + hl:]
            off = meta.get("off")
            cap_srv = meta["cap"] + off if off is not None else None
            lat = t_recv - cap_srv if cap_srv is not None else None
            meta.update({"ts": cap_srv if cap_srv is not None else t_recv, "recv": t_recv, "lat_ms": None if lat is None else round(lat)})
            latest["jpeg"], latest["meta"] = jpeg, meta
            writer.write(ws_frame(0x1, json.dumps({"type": "ack", "seq": meta["seq"], "ts": int(t_recv)}).encode()))
            await writer.drain()
            stats["frames"] += 1
            stats["bytes"] += len(jpeg)
            if lat is not None:
                stats["lat_sum"] += lat
                stats["lat_n"] += 1
            stats["enc_ms"] = meta.get("enc")
            new_frame.set()
            new_frame.clear()
            t = time.time()
            if t - stats["t"] >= 1:
                dt = t - stats["t"]
                stats["fps"] = round(stats["frames"] / dt, 1)
                stats["kb"] = round(stats["bytes"] / max(1, stats["frames"]) / 1024, 1)
                stats["lat_ms"] = round(stats["lat_sum"] / stats["lat_n"]) if stats["lat_n"] else None
                print(f"{stats['fps']} fps  {stats['kb']} KB/frame  capture→relay {stats['lat_ms']} ms  "
                      f"enc {stats['enc_ms']} ms  {meta['w']}x{meta['h']}  viewers {stats['viewers']}", flush=True)
                stats.update({"frames": 0, "bytes": 0, "lat_sum": 0.0, "lat_n": 0, "t": t})
    except (asyncio.IncompleteReadError, ConnectionError):
        pass
    finally:
        stats["glasses"] -= 1
        print("glasses disconnected", flush=True)


async def viewer_ws(reader, writer):
    stats["viewers"] += 1
    sent_seq = -1
    try:
        while True:
            if latest["meta"] is None or latest["meta"]["seq"] == sent_seq:
                await new_frame.wait()
                continue
            meta, jpeg = latest["meta"], latest["jpeg"]
            sent_seq = meta["seq"]
            head = {k: meta.get(k) for k in ("ts", "seq", "lat_ms", "rot", "w", "h")}
            writer.write(ws_frame(0x1, json.dumps(head).encode()))
            writer.write(ws_frame(0x2, jpeg))
            await writer.drain()            # a slow viewer blocks here; newer frames simply replace older ones
    except (ConnectionError, asyncio.IncompleteReadError):
        pass
    finally:
        stats["viewers"] -= 1


async def mjpeg(writer):
    writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: multipart/x-mixed-replace; boundary=frame\r\n"
                 b"Cache-Control: no-store\r\nAccess-Control-Allow-Origin: *\r\n\r\n")
    sent = -1
    try:
        while True:
            if latest["meta"] is None or latest["meta"]["seq"] == sent:
                await new_frame.wait()
                continue
            sent, jpeg = latest["meta"]["seq"], latest["jpeg"]
            writer.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n")
            await writer.drain()
    except ConnectionError:
        pass


VIEW = """<!doctype html><meta charset=utf-8><title>Glasses camera</title>
<body style="margin:0;background:#000;color:#9f9;font:14px monospace">
<canvas id=c style="max-width:100vw;max-height:92vh;display:block;margin:auto"></canvas><div id=s style="text-align:center"></div>
<script>
var c=document.getElementById('c'),x=c.getContext('2d'),s=document.getElementById('s'),meta=null,lats=[],n=0,t0=performance.now();
var ws=new WebSocket('ws://'+location.host+'/ws/camera');ws.binaryType='blob';
ws.onmessage=function(e){ if(typeof e.data==='string'){meta=JSON.parse(e.data);return;}
  var m=meta; createImageBitmap(e.data).then(function(b){ var r=(m&&m.rot)||0, sw=r%180?b.height:b.width, sh=r%180?b.width:b.height;
    c.width=sw;c.height=sh;x.save();x.translate(sw/2,sh/2);x.rotate(r*Math.PI/180);x.drawImage(b,-b.width/2,-b.height/2);x.restore();
    requestAnimationFrame(function(){ var l=Date.now()-m.ts; lats.push(l); if(lats.length>30)lats.shift(); n++;
      var dt=(performance.now()-t0)/1000; if(dt>1){ s.textContent='capture→screen '+Math.round(lats.reduce(function(a,b){return a+b},0)/lats.length)+' ms  ·  '+(n/dt).toFixed(1)+' fps  ·  capture→relay '+m.lat_ms+' ms  ·  '+m.w+'x'+m.h; n=0;t0=performance.now(); }});
  });};
</script>"""


async def handle(reader, writer):
    try:
        req = await reader.readuntil(b"\r\n\r\n")
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError):
        writer.close(); return
    lines = req.decode("latin-1").split("\r\n")
    method, path = (lines[0].split(" ") + ["", ""])[:2]
    headers = {l.split(":", 1)[0].strip().lower(): l.split(":", 1)[1].strip() for l in lines[1:] if ":" in l}
    path = path.split("?")[0]
    try:
        if headers.get("upgrade", "").lower() == "websocket":
            await upgrade(writer, headers)
            if path in ("/glasses/camera/ws", "/ingest"):
                await ingest(reader, writer)
            else:
                await viewer_ws(reader, writer)
        elif path == "/camera.mjpg":
            await mjpeg(writer)
        elif path == "/camera.jpg" and latest["jpeg"]:
            j = latest["jpeg"]
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: image/jpeg\r\nAccess-Control-Allow-Origin: *\r\nContent-Length: "
                         + str(len(j)).encode() + b"\r\n\r\n" + j)
        elif path == "/stats":
            body = json.dumps({k: v for k, v in stats.items() if k not in ("lat_sum", "lat_n", "bytes", "frames", "t")}
                              | {"last": latest["meta"]}).encode()
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\nContent-Length: "
                         + str(len(body)).encode() + b"\r\n\r\n" + body)
        elif path in ("/", "/view"):
            b = VIEW.encode()
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: " + str(len(b)).encode() + b"\r\n\r\n" + b)
        else:
            writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
        await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def main():
    global new_frame
    new_frame = asyncio.Event()
    server = await asyncio.start_server(handle, "0.0.0.0", PORT, limit=1 << 20)
    print(f"camera relay on :{PORT}  (view: http://localhost:{PORT}/view)", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
