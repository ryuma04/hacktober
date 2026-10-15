"""Gemma 4 client for the Gemini API (Google AI Studio).

* Key pool: GEMINI_API_KEYS (comma/newline separated). A key that hits its quota (429) is cooled down and the next
  key is used immediately; a rejected key (400 invalid / 401 / 403) is retired. Keys are re-read from .env on every
  call, so new keys can be added while the service runs.
* Model fallback: GEMMA_MODELS tried in order when a model is overloaded (500/503/504).
* JSON: Gemma replies are plain text; we skip "thought" parts, extract the first JSON value, validate it with
  pydantic and retry once with the validation error.
* Every call is logged to <job_dir>/ai_calls.jsonl with the raw prompt/response under <job_dir>/ai/.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from . import config

log = logging.getLogger("depexit.gemma")
API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
T = TypeVar("T", bound=BaseModel)


class GemmaUnavailable(Exception):
    pass


# ---------------- key pool ----------------

@dataclass
class _KeyState:
    cooldown_until: float = 0.0
    dead: bool = False
    reason: str = ""


class KeyPool:
    def __init__(self) -> None:
        self._state: dict[str, _KeyState] = {}
        self._cursor = 0
        self._lock = threading.Lock()

    @staticmethod
    def configured() -> list[str]:
        raw = config.get("GEMINI_API_KEYS") + "," + config.get("GEMINI_API_KEY")
        keys, seen = [], set()
        for k in re.split(r"[,\s]+", raw):
            k = k.strip()
            if k and k not in seen:
                seen.add(k)
                keys.append(k)
        return keys

    def next_key(self, exclude: set[str]) -> str | None:
        keys = self.configured()
        now = time.time()
        with self._lock:
            n = len(keys)
            for i in range(n):
                k = keys[(self._cursor + i) % n]
                st = self._state.setdefault(k, _KeyState())
                if k in exclude or st.dead or st.cooldown_until > now:
                    continue
                self._cursor = (self._cursor + i + 1) % n  # round-robin spreads load across keys
                return k
        return None

    def cooldown(self, key: str, seconds: float, reason: str) -> None:
        with self._lock:
            st = self._state.setdefault(key, _KeyState())
            st.cooldown_until = time.time() + seconds
            st.reason = reason
        log.warning("key …%s cooled down %ss: %s", key[-6:], int(seconds), reason)

    def retire(self, key: str, reason: str) -> None:
        with self._lock:
            st = self._state.setdefault(key, _KeyState())
            st.dead, st.reason = True, reason
        log.warning("key …%s retired: %s", key[-6:], reason)

    def status(self) -> dict:
        keys = self.configured()
        now = time.time()
        usable = [k for k in keys if not self._state.get(k, _KeyState()).dead
                  and self._state.get(k, _KeyState()).cooldown_until <= now]
        return {"configured": len(keys), "usable": len(usable),
                "retired": sum(1 for k in keys if self._state.get(k, _KeyState()).dead)}


POOL = KeyPool()


def models() -> list[str]:
    return [m.strip() for m in config.get("GEMMA_MODELS", "gemma-4-26b-a4b-it,gemma-4-31b-it").split(",") if m.strip()]


# ---------------- call log ----------------

@dataclass
class CallLog:
    job_dir: Path | None
    calls: list[dict] = field(default_factory=list)
    _n: int = 0

    def record(self, purpose: str, model: str, latency_ms: int, ok: bool, prompt: str, reply: str,
               error: str | None = None, attempts: int = 1) -> dict:
        self._n += 1
        rec = {"purpose": purpose, "model": model, "latency_ms": latency_ms, "ok": ok, "attempts": attempts,
               "prompt_chars": len(prompt), "output_chars": len(reply)}
        if error:
            rec["error"] = error[:300]
        self.calls.append(rec)
        if self.job_dir:
            try:
                ai_dir = self.job_dir / "ai"
                ai_dir.mkdir(parents=True, exist_ok=True)
                safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", purpose)[:60]
                (ai_dir / f"{int(time.time()*1000)}_{safe}.txt").write_text(
                    f"MODEL: {model}\nOK: {ok}\nERROR: {error or ''}\n\n=== PROMPT ===\n{prompt}\n\n=== REPLY ===\n{reply}\n",
                    encoding="utf-8")
                with open(self.job_dir / "ai_calls.jsonl", "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(rec) + "\n")
            except OSError:
                pass
        return rec


# ---------------- transport ----------------

_client: httpx.AsyncClient | None = None
_sem: asyncio.Semaphore | None = None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        t = float(config.get("GEMMA_TIMEOUT_S", "120"))
        _client = httpx.AsyncClient(timeout=httpx.Timeout(20.0, read=t))
    return _client


def _semaphore() -> asyncio.Semaphore:
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(int(config.get("GEMMA_MAX_CONCURRENCY", "6")))
    return _sem


def configured() -> bool:
    return bool(KeyPool.configured()) or bool(config.get("XAI_API_KEYS").strip())


async def generate(prompt: str, temperature: float = 0.2, max_tokens: int = 8192) -> tuple[str, str, int]:
    """Return (text, model, attempts). Rotates keys on quota/auth errors and models on overload."""
    if not configured():
        raise GemmaUnavailable("no GEMINI_API_KEYS configured")
    if not KeyPool.configured():  # only the fallback provider is configured
        fb = await _grok(prompt, temperature, max_tokens)
        if fb:
            return fb[0], fb[1], 1
        raise GemmaUnavailable("no GEMINI_API_KEYS configured and fallback provider unavailable")
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens}}
    stats = {"attempts": 0, "last_err": "unknown error"}

    async def try_model(model: str) -> tuple[str, str]:
        """Rotate keys for one model; return (text, model) or raise GemmaUnavailable."""
        tried_keys: set[str] = set()
        while True:
            key = POOL.next_key(tried_keys)
            if key is None:
                raise GemmaUnavailable(stats["last_err"])
            tried_keys.add(key)
            stats["attempts"] += 1
            try:
                r = await _http().post(API.format(model=model), json=body, headers={"x-goog-api-key": key})
            except httpx.HTTPError as e:
                stats["last_err"] = f"{model}: {type(e).__name__}"
                raise GemmaUnavailable(stats["last_err"])
            if r.status_code == 200:
                data = r.json()
                cands = data.get("candidates") or []
                parts = (cands[0].get("content") or {}).get("parts", []) if cands else []
                text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
                if text.strip():
                    return text, model
                stats["last_err"] = f"{model}: empty reply ({cands[0].get('finishReason') if cands else 'no candidates'})"
                continue  # transient: retry the same model on the next key
            msg = _err_msg(r)
            stats["last_err"] = f"{model}: HTTP {r.status_code} {msg}"
            if r.status_code == 429:
                daily = "day" in msg.lower() or "PerDay" in msg
                POOL.cooldown(key, 3600 * 6 if daily else 60, msg)
                continue  # same model, next key
            if r.status_code in (401, 403) or (r.status_code == 400 and "key" in msg.lower()):
                POOL.retire(key, msg)
                continue
            raise GemmaUnavailable(stats["last_err"])  # 404 / overloaded 5xx / bad request: give up on this model

    if True:  # concurrency is limited by the caller (complete_json / health)
        for round_ in range(2):
            # Hedged request: all models race (each on its own key); the first valid reply wins, the rest are cancelled.
            tasks = [asyncio.create_task(try_model(m)) for m in models()]
            try:
                for fut in asyncio.as_completed(tasks):
                    try:
                        text, model = await fut
                        return text, model, stats["attempts"]
                    except GemmaUnavailable:
                        continue
            finally:
                for t in tasks:
                    t.cancel()
            if not POOL.next_key(set()):
                break
            await asyncio.sleep(3)
        fallback = await _grok(prompt, temperature, max_tokens)
        if fallback:
            return fallback[0], fallback[1], stats["attempts"] + 1
    raise GemmaUnavailable(stats["last_err"])


XAI_POOL = KeyPool()


async def _grok(prompt: str, temperature: float, max_tokens: int) -> tuple[str, str] | None:
    """Last-resort fallback (xAI Grok, OpenAI-compatible). Recorded under its own model name in the call log."""
    keys = [k for k in re.split(r"[,\s]+", config.get("XAI_API_KEYS")) if k]
    model = config.get("XAI_MODEL", "grok-3-mini")
    tried: set[str] = set()
    for _ in keys:
        key = next((k for k in keys if k not in tried and not XAI_POOL._state.get(k, _KeyState()).dead
                    and XAI_POOL._state.get(k, _KeyState()).cooldown_until <= time.time()), None)
        if not key:
            return None
        tried.add(key)
        try:
            r = await _http().post("https://api.x.ai/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                                   json={"model": model, "temperature": temperature, "max_tokens": max_tokens,
                                         "messages": [{"role": "user", "content": prompt}]})
        except httpx.HTTPError:
            return None
        if r.status_code == 200:
            text = r.json()["choices"][0]["message"].get("content") or ""
            return (text, f"xai:{model}") if text.strip() else None
        msg = _err_msg(r) or r.text[:200]
        if r.status_code == 429:
            XAI_POOL.cooldown(key, 60, msg)
        else:
            XAI_POOL.retire(key, msg)  # credits exhausted / invalid key
    return None


def _err_msg(r: httpx.Response) -> str:
    try:
        err = r.json().get("error") or ""
    except (ValueError, AttributeError):
        return r.text[:300]
    return (err.get("message", "") if isinstance(err, dict) else str(err))[:300]


# ---------------- JSON helpers ----------------

def extract_json(text: str):
    t = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", t, re.DOTALL)
    if fence:
        t = fence.group(1).strip()
    for opener in ("{", "["):
        start = t.find(opener)
        if start == -1:
            continue
        depth, in_str, esc = 0, False, False
        closer = "}" if opener == "{" else "]"
        for i in range(start, len(t)):
            c = t[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == opener:
                depth += 1
            elif c == closer:
                depth -= 1
                if depth == 0:
                    return json.loads(t[start:i + 1])
    return json.loads(t)


async def complete_json(log_: CallLog, purpose: str, prompt: str, schema: type[T],
                        max_tokens: int = 8192, deadline_s: float = 180) -> T | None:
    """Ask Gemma for JSON matching `schema` within `deadline_s` (total, including one repair retry).
    Returns None (and logs a failed call) if Gemma is unavailable or too slow; callers fall back deterministically."""
    async with _semaphore():
        return await _complete_json(log_, purpose, prompt, schema, max_tokens, deadline_s)


async def _complete_json(log_: CallLog, purpose: str, prompt: str, schema: type[T], max_tokens: int,
                         deadline_s: float) -> T | None:
    current = prompt
    t_start = time.time()
    for attempt in range(2):
        t0 = time.time()
        remaining = deadline_s - (t0 - t_start)
        if remaining < 15:
            return None
        try:
            text, model, n = await asyncio.wait_for(generate(current, max_tokens=max_tokens), timeout=remaining)
        except asyncio.TimeoutError:
            log_.record(purpose, ",".join(models()), int((time.time() - t0) * 1000), False, current, "",
                        f"timed out after {int(remaining)}s (deterministic fallback used)")
            return None
        except GemmaUnavailable as e:
            log_.record(purpose, ",".join(models()), int((time.time() - t0) * 1000), False, current, "", str(e))
            return None
        try:
            obj = schema.model_validate(extract_json(text))
            log_.record(purpose, model, int((time.time() - t0) * 1000), True, current, text, attempts=n)
            return obj
        except (ValueError, ValidationError) as e:
            err = str(e)[:600]
            log_.record(purpose, model, int((time.time() - t0) * 1000), False, current, text,
                        f"invalid JSON: {err}", attempts=n)
            current = (prompt + f"\n\nYour previous reply was invalid: {err}\n"
                       "Reply with ONLY the corrected JSON object, nothing else.")
    return None
