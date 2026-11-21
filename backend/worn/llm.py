"""Local Ollama client. Strict JSON, timeouts, one retry, and the 14b -> 7b fallback:
qwen2.5:14b gets TUTOR_BUDGET seconds (3 s); if it is slower or fails, qwen2.5:7b answers instead.
All models are kept warm (keep_alive) so the demo never sees a cold start."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, Callable

import httpx

from . import config

log = logging.getLogger("worn.llm")

_client: httpx.AsyncClient | None = None
status: dict[str, Any] = {"warm": {}, "last": {}}  # surfaced by /health


def client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(base_url=config.OLLAMA_URL, timeout=60)
    return _client


class LLMError(RuntimeError):
    pass


def parse_json(text: str) -> dict:
    text = (text or "").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise ValueError(f"no JSON object in model output: {text[:120]!r}")
        data = json.loads(m.group(0))
    if not isinstance(data, dict):
        raise ValueError("model output is not a JSON object")
    return data


def num_ctx(model: str) -> int:
    """Small fixed contexts: at Ollama's 32k default the 14b alone takes 15 GB and evicts the vision
    model on a 32 GB Mac. Changing num_ctx reloads a model, so warm-up uses the same values."""
    return config.VISION_CTX if model == config.VISION_MODEL else config.TUTOR_CTX


async def _generate(model: str, prompt: str, *, system: str | None, images: list[str] | None,
                    timeout: float, temperature: float, num_predict: int) -> str:
    body: dict[str, Any] = {
        "model": model, "prompt": prompt, "format": "json", "stream": False,
        "keep_alive": config.KEEP_ALIVE,
        "options": {"temperature": temperature, "num_predict": num_predict, "num_ctx": num_ctx(model)},
    }
    if system:
        body["system"] = system
    if images:
        body["images"] = images
    r = await client().post("/api/generate", json=body, timeout=timeout)
    r.raise_for_status()
    return r.json().get("response", "")


async def json_call(model: str, prompt: str, *, system: str | None = None, images: list[str] | None = None,
                    timeout: float = 10, validate: Callable[[dict], dict] | None = None,
                    temperature: float = 0.2, num_predict: int = 256, retries: int = 1) -> dict:
    """One model, strict JSON, retry once on a bad/invalid answer or a transport error.
    Raises LLMError when every attempt fails; asyncio.TimeoutError propagates for the caller's budget."""
    last: Exception | None = None
    ask = prompt
    for attempt in range(retries + 1):
        t0 = time.perf_counter()
        try:
            text = await _generate(model, ask, system=system, images=images, timeout=timeout,
                                   temperature=temperature, num_predict=num_predict)
            data = parse_json(text)
            data = validate(data) if validate else data
            status["last"][model] = {"ms": int((time.perf_counter() - t0) * 1000), "ok": True, "ts": time.time()}
            return data
        except (httpx.TimeoutException, asyncio.TimeoutError):
            status["last"][model] = {"ms": int((time.perf_counter() - t0) * 1000), "ok": False, "error": "timeout"}
            raise asyncio.TimeoutError(f"{model} timed out after {timeout}s")
        except (ValueError, KeyError, TypeError, httpx.HTTPError) as e:
            last = e
            log.warning("%s attempt %d failed: %s", model, attempt + 1, e)
            # The retry tells the model what was wrong (same prompt at temp 0 just repeats the mistake).
            ask = f"{prompt}\n\nYour previous answer was rejected: {str(e)[:160]}. Fix exactly that. JSON only."
            status["last"][model] = {"ms": int((time.perf_counter() - t0) * 1000), "ok": False, "error": str(e)[:200]}
    raise LLMError(f"{model}: {last}")


async def tutor_json(prompt: str, *, system: str | None = None, validate: Callable[[dict], dict] | None = None,
                     num_predict: int = 256, temperature: float = 0.3) -> tuple[dict, dict]:
    """qwen2.5:14b within TUTOR_BUDGET (3 s), else qwen2.5:7b, as a HEDGED request: if 14b hasn't
    answered after HEDGE_AFTER seconds, 7b starts in parallel. At the budget we take 14b if it's
    done, otherwise 7b (usually already finished). Worst case ~= budget instead of budget + 7b.
    Returns (data, meta) with meta = {model, ms, fallback, reason}. Raises LLMError if both fail."""
    t0 = time.perf_counter()
    kw = dict(system=system, validate=validate, num_predict=num_predict, temperature=temperature)
    big = asyncio.create_task(json_call(config.TUTOR_MODEL, prompt, timeout=config.TUTOR_BUDGET + 2, **kw))
    small: asyncio.Task | None = None

    def meta(model: str, fallback: bool, reason: str | None = None) -> dict:
        m = {"model": model, "ms": int((time.perf_counter() - t0) * 1000), "fallback": fallback}
        if reason:
            m["reason"] = reason
        return m

    def start_small():
        nonlocal small
        if small is None:
            small = asyncio.create_task(json_call(config.TUTOR_FALLBACK, prompt, timeout=config.FALLBACK_TIMEOUT, **kw))

    reason = None
    try:
        done, _ = await asyncio.wait({big}, timeout=min(config.HEDGE_AFTER, config.TUTOR_BUDGET))
        if not done:
            start_small()
            remaining = config.TUTOR_BUDGET - (time.perf_counter() - t0)
            done, _ = await asyncio.wait({big}, timeout=max(0.0, remaining))
        if big in done and big.exception() is None:
            if small:
                small.cancel()
            return big.result(), meta(config.TUTOR_MODEL, False)
        reason = (f"{config.TUTOR_MODEL} exceeded {config.TUTOR_BUDGET:g}s" if big not in done
                  else f"{config.TUTOR_MODEL} failed: {str(big.exception())[:120]}")
    finally:
        if not big.done():
            big.cancel()
    log.info("tutor fallback: %s", reason)
    start_small()
    left = min(config.FALLBACK_TIMEOUT, config.DECIDE_CAP - (time.perf_counter() - t0))
    try:
        data = await asyncio.wait_for(small, timeout=max(0.05, left))
    except (asyncio.TimeoutError, LLMError) as e:
        raise LLMError(f"{reason}; {config.TUTOR_FALLBACK}: {e or 'timed out'}") from e
    return data, meta(config.TUTOR_FALLBACK, True, reason)


async def vision_json(prompt: str, jpeg_b64: str, *, validate: Callable[[dict], dict] | None = None) -> tuple[dict, dict]:
    t0 = time.perf_counter()
    data = await json_call(config.VISION_MODEL, prompt, images=[jpeg_b64], timeout=config.GRADE_TIMEOUT,
                           validate=validate, temperature=0.1, num_predict=160)
    return data, {"model": config.VISION_MODEL, "ms": int((time.perf_counter() - t0) * 1000)}


# ------------------------------------------------------------------ warmth

async def warm_once() -> None:
    for model in (config.VISION_MODEL, config.TUTOR_MODEL, config.TUTOR_FALLBACK):
        t0 = time.perf_counter()
        try:
            r = await client().post("/api/generate", json={"model": model, "prompt": "", "keep_alive": config.KEEP_ALIVE,
                                                           "options": {"num_ctx": num_ctx(model)}}, timeout=180)
            r.raise_for_status()
            status["warm"][model] = {"ok": True, "ms": int((time.perf_counter() - t0) * 1000), "ts": time.time()}
        except Exception as e:
            status["warm"][model] = {"ok": False, "error": str(e)[:200], "ts": time.time()}
            log.warning("could not warm %s: %s", model, e)


async def keep_warm(interval: float = 600) -> None:
    while True:
        await warm_once()
        await asyncio.sleep(interval)


async def loaded_models() -> list[str]:
    try:
        r = await client().get("/api/ps", timeout=2)
        return [m.get("name") for m in r.json().get("models", [])]
    except Exception:
        return []
