#!/usr/bin/env python3
"""Expose the IPv4-only backend (127.0.0.1:8000) on the Mac's IPv6 address, for hotspots that give the Mac
IPv6 only (iPhone Personal Hotspot without Maximize Compatibility). Plain TCP relay, standard library only.
    python3 glasses-android/tools/v6_bridge.py [port]     # default 8000 → 127.0.0.1:8000"""
import asyncio, socket, sys
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000

async def pipe(r, w):
    try:
        while True:
            b = await r.read(65536)
            if not b: break
            w.write(b); await w.drain()
    except Exception: pass
    finally:
        try: w.close()
        except Exception: pass

async def handle(cr, cw):
    try:
        br, bw = await asyncio.open_connection("127.0.0.1", PORT)
    except Exception:
        cw.close(); return
    await asyncio.gather(pipe(cr, bw), pipe(br, cw))

async def main():
    s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("::", PORT)); s.listen(64); s.setblocking(False)
    server = await asyncio.start_server(handle, sock=s)
    print(f"IPv6 [::]:{PORT} -> 127.0.0.1:{PORT}", flush=True)
    async with server: await server.serve_forever()

asyncio.run(main())
