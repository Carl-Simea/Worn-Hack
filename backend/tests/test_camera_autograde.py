"""Camera relay (WS + MJPEG + HTTP) and automatic grading from preview frames (models mocked)."""

from __future__ import annotations

import asyncio
import time

import cv2
import numpy as np
import pytest

from test_routes import fake  # noqa: F401  (fixture)
from worn import autograde, strokes
from worn.camera import RELAY, mjpeg


def frame(lang: str, char: str, n_strokes: int, jitter: int = 0) -> bytes:
    """Paper with the first n template strokes drawn in pen (what the glasses camera sees while writing)."""
    img = np.full((480, 640, 3), (216, 231, 236), np.uint8)
    tm = strokes.template(lang, char)
    for s in tm["strokes"][:n_strokes]:
        cv2.polylines(img, [(s * 380 + [130 + jitter, 50]).astype(np.int32)], False, (40, 25, 25), 9)
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()


def test_ws_relay_fans_out_latest_frame(client):
    with client.websocket_connect("/ws/camera?role=view") as viewer:
        with client.websocket_connect("/ws/camera?role=pub") as pub:
            pub.send_json({"ts": 1763700000123, "w": 640, "h": 480})
            pub.send_bytes(frame("mandarin", "一", 0))
            meta = viewer.receive_json()
            jpg = viewer.receive_bytes()
    assert jpg[:2] == b"\xff\xd8" and meta["w"] == 640 and abs(meta["ts"] - 1763700000.123) < 1e-3
    r = client.get("/camera.jpg")
    assert r.status_code == 200 and r.content == jpg and r.headers["x-frame-seq"]
    st = client.get("/camera/status").json()
    assert st["seq"] >= 1 and st["size"] == len(jpg)


def test_http_publish_and_base64_frames(client):
    f = frame("mandarin", "一", 1)
    assert client.post("/camera/frame", files={"image": ("f.jpg", f, "image/jpeg")}).json()["ok"]
    import base64
    with client.websocket_connect("/ws/camera") as ws:  # no role: becomes a publisher by sending
        ws.send_json({"ts": time.time(), "jpeg": "data:image/jpeg;base64," + base64.b64encode(f).decode()})
        time.sleep(0.2)
    assert client.get("/camera.jpg").content == f
    assert client.post("/camera/frame", files={"image": ("f.jpg", b"nope", "image/jpeg")}).status_code == 400


def test_mjpeg_yields_newest_frame_only():
    async def go():
        gen = mjpeg()
        await RELAY.publish(frame("mandarin", "一", 0))
        await RELAY.publish(frame("mandarin", "一", 1))  # two frames before the viewer reads: only the newest
        part = await gen.__anext__()
        await gen.aclose()
        return part
    part = asyncio.run(go())
    assert part.startswith(b"--wornframe") and part.endswith(b"\r\n") and RELAY.jpeg in part


def _wait_phase(client, phase: str, timeout: float = 15) -> dict:
    t = time.time()
    while time.time() - t < timeout:
        g = client.get("/app-state").json().get("grading") or {}
        if g.get("phase") == phase:
            return g
        time.sleep(0.05)
    raise AssertionError(f"never reached {phase}: {client.get('/app-state').json().get('grading')}")


@pytest.fixture
def auto(client, monkeypatch):
    monkeypatch.setattr(autograde, "SETTLE_S", 0.5)
    monkeypatch.setattr(autograde, "STILL_WAIT_S", 0.2)
    monkeypatch.setattr(autograde, "MIN_INTERVAL", 0.0)
    client.post("/reset")
    return client


def _start(client, lang, item):
    client.post("/session", json={"lang": lang, "item_id": item})
    client.post("/app-state", json={"screen": "lesson", "phase": "your_turn"})


def _push(client, jpg):
    client.post("/camera/frame", files={"image": ("f.jpg", jpg, "image/jpeg")})
    time.sleep(0.25)  # the grader processes frames in the background


def test_auto_grade_scores_each_stroke_then_grades_itself(auto, fake):
    _start(auto, "mandarin", "water")  # 水: 4 strokes
    _push(auto, frame("mandarin", "水", 0))
    assert _wait_phase(auto, "watching")["stroke_count"] == 4
    seen = []
    for n in range(1, 5):
        _push(auto, frame("mandarin", "水", n))
        g = auto.get("/app-state").json()["grading"]
        seen.append((g["phase"], g.get("accuracy")))
    assert any(p == "stroke_scored" and a is not None for p, a in seen)
    res = _wait_phase(auto, "result")
    assert res["score"] is not None
    last = auto.get("/live/state").json()["last_result"]
    assert last["source"] == "preview" and last["status"] == "ok" and last["subscores"]
    steps = [s for s in auto.get("/live/state").json()["agent_steps"] if s.get("tool") == "t2"]
    assert steps and "Stroke" in steps[0]["summary"]


def test_auto_final_after_ink_settles(auto, fake):
    _start(auto, "mandarin", "hello")  # 你: 7 strokes; stop after 3
    _push(auto, frame("mandarin", "你", 0))
    _wait_phase(auto, "watching")
    _push(auto, frame("mandarin", "你", 3))
    g = _wait_phase(auto, "analyzing", timeout=5)
    assert g["capture_request"]["id"] and "still" in g["reason"]
    _wait_phase(auto, "result")


def test_still_answers_capture_request(auto, fake):
    _start(auto, "mandarin", "one")  # 一: one stroke → done → analyzing, waits for a still
    autograde.STILL_WAIT_S = 3.0
    _push(auto, frame("mandarin", "一", 0))
    _wait_phase(auto, "watching")
    _push(auto, frame("mandarin", "一", 1))
    _wait_phase(auto, "analyzing", timeout=5)
    r = auto.post("/grade", files={"image": ("s.jpg", frame("mandarin", "一", 1), "image/jpeg")}).json()
    assert r["source"] == "still"
    assert _wait_phase(auto, "result")["score"] == r["score"]


def test_camera_wobble_and_hand_are_not_strokes(auto, fake):
    _start(auto, "mandarin", "water")
    _push(auto, frame("mandarin", "水", 0))
    _wait_phase(auto, "watching")
    _push(auto, frame("mandarin", "水", 0, jitter=4))  # camera moved a little, no new ink
    hand = cv2.imdecode(np.frombuffer(frame("mandarin", "水", 0), np.uint8), cv2.IMREAD_COLOR)
    cv2.rectangle(hand, (300, 150), (640, 480), (60, 80, 120), -1)  # a hand over the page
    _push(auto, cv2.imencode(".jpg", hand)[1].tobytes())
    assert auto.get("/app-state").json()["grading"]["phase"] == "watching"
