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
import hashlib
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
    strikes: int = 0  # consecutive 429s; a key that keeps failing right after cooling down is out for the day


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

    def rate_limited(self, key: str, reason: str) -> None:
        """HTTP 429. Google uses the same message for per-minute and daily quotas, so escalate on repeats:
        60 s cool-downs first, and after DAILY_STRIKES consecutive 429s treat the key as out for the day."""
        with self._lock:
            st = self._state.setdefault(key, _KeyState())
            st.strikes += 1
            daily = st.strikes >= DAILY_STRIKES
            seconds = 6 * 3600 if daily else 60
            st.cooldown_until = time.time() + seconds
            st.reason = ("daily quota likely exhausted: " if daily else "per-minute rate limit: ") + reason
        log.warning("key …%s cooled down %ss (strike %s): %s", key[-4:], int(seconds), st.strikes, reason)

    def succeeded(self, key: str) -> None:
        with self._lock:
            self._state.setdefault(key, _KeyState()).strikes = 0

    def soonest_available(self) -> float | None:
        """Seconds until some key leaves a short cool-down; None if every key is retired or out for the day."""
        now = time.time()
        waits = [max(0.0, st.cooldown_until - now) for k in self.configured()
                 for st in [self._state.get(k, _KeyState())] if not st.dead and st.strikes < DAILY_STRIKES]
        return min(waits) if waits else None

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
        detail = []
        for k in keys:
            st = self._state.get(k, _KeyState())
            state = "retired" if st.dead else ("cooling_down" if st.cooldown_until > now else "ok")
            detail.append({"key": "…" + k[-4:], "state": state, "reason": st.reason[:120] if state != "ok" else ""})
        return {"configured": len(keys), "usable": len(usable),
                "retired": sum(1 for k in keys if self._state.get(k, _KeyState()).dead),
                "exhausted": bool(keys) and self.soonest_available() is None, "detail": detail}


DAILY_STRIKES = 4
POOL = KeyPool()
KEYS_EXHAUSTED = "ALL GEMINI API KEYS EXHAUSTED OR REJECTED - add new keys to GEMINI_API_KEYS in .env (picked up without restart)"


def models() -> list[str]:
    return [m.strip() for m in config.get("GEMMA_MODELS", "gemma-4-26b-a4b-it,gemma-4-31b-it").split(",") if m.strip()]


# ---------------- call log ----------------

@dataclass
class CallLog:
    job_dir: Path | None
    calls: list[dict] = field(default_factory=list)
    _n: int = 0

    def record(self, purpose: str, model: str, latency_ms: int, ok: bool, prompt: str, reply: str,
               error: str | None = None, attempts: int = 1, cached: bool = False) -> dict:
        self._n += 1
        rec = {"purpose": purpose, "model": model, "latency_ms": latency_ms, "ok": ok, "attempts": attempts,
               "prompt_chars": len(prompt), "output_chars": len(reply), "cached": cached}
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
        _client = httpx.AsyncClient(timeout=httpx.Timeout(20.0, read=min(t, 90.0)))
    return _client


def _semaphore() -> asyncio.Semaphore:
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(int(config.get("GEMMA_MAX_CONCURRENCY", "6")))
    return _sem


def configured() -> bool:
    return bool(KeyPool.configured()) or any(_provider_keys(n) for n in OPENAI_COMPAT)


def fallback_models() -> list[str]:
    """Non-Gemma Gemini models used only when Gemma 4 fails or misses its time budget."""
    return [m.strip() for m in config.get("FALLBACK_MODELS", "gemini-3.5-flash,gemini-3.1-flash-lite").split(",")
            if m.strip()]


def _abandon(task: asyncio.Future) -> None:
    """Cancel without waiting (a slow HTTP read must never hold up the pipeline) and silence its late result."""
    task.cancel()
    task.add_done_callback(lambda f: f.cancelled() or f.exception())


async def generate(prompt: str, temperature: float = 0.2, max_tokens: int = 8192,
                   model_list: list[str] | None = None) -> tuple[str, str, int]:
    """Return (text, model, attempts) from the Gemini API (Gemma 4 models by default). Rotates keys on quota/auth
    errors and hedges to the next model when the first is slow. Raises GemmaUnavailable."""
    if not KeyPool.configured():
        raise GemmaUnavailable("no GEMINI_API_KEYS configured")
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens}}
    stats = {"attempts": 0, "last_err": "unknown error"}

    async def try_model(model: str) -> tuple[str, str]:
        """Rotate keys for one model; return (text, model) or raise GemmaUnavailable."""
        tried_keys: set[str] = set()
        overload_retries = [3, 8]  # Google returns 500/503 "high demand" in bursts; brief backoff usually clears it
        while True:
            key = POOL.next_key(tried_keys)
            if key is None:
                wait = POOL.soonest_available()
                if wait is None:
                    stats["last_err"] = KEYS_EXHAUSTED
                    log.error(KEYS_EXHAUSTED + " %s", POOL.status())
                    raise GemmaUnavailable(stats["last_err"])
                if POOL.next_key(set()) is None:  # every key is briefly rate-limited: wait, the deadline still applies
                    await asyncio.sleep(min(wait, 65) + 0.5)
                    tried_keys.clear()
                    continue
                raise GemmaUnavailable(stats["last_err"])
            tried_keys.add(key)
            stats["attempts"] += 1
            try:
                r = await _http().post(API.format(model=model), json=body, headers={"x-goog-api-key": key})
            except httpx.ReadTimeout:
                stats["last_err"] = f"{model}: read timeout"
                raise GemmaUnavailable(stats["last_err"])
            except httpx.HTTPError as e:
                stats["last_err"] = f"{model}: {type(e).__name__}"
                if overload_retries:
                    await asyncio.sleep(overload_retries.pop(0))
                    tried_keys.discard(key)
                    continue
                raise GemmaUnavailable(stats["last_err"])
            if r.status_code == 200:
                data = r.json()
                cands = data.get("candidates") or []
                parts = (cands[0].get("content") or {}).get("parts", []) if cands else []
                text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
                if text.strip():
                    POOL.succeeded(key)
                    return text, model
                stats["last_err"] = f"{model}: empty reply ({cands[0].get('finishReason') if cands else 'no candidates'})"
                continue  # transient: retry the same model on the next key
            msg = _err_msg(r)
            stats["last_err"] = f"{model}: HTTP {r.status_code} {msg}"
            if r.status_code == 429:
                POOL.rate_limited(key, msg)
                continue  # same model, next key
            if r.status_code in (401, 403) or (r.status_code == 400 and "key" in msg.lower()):
                POOL.retire(key, msg)
                continue
            if r.status_code in (500, 502, 503, 504) and overload_retries:
                await asyncio.sleep(overload_retries.pop(0))
                tried_keys.discard(key)  # the key is fine; the model was busy
                continue
            raise GemmaUnavailable(stats["last_err"])  # 404 / persistent overload / bad request: give up on this model

    if True:  # concurrency is limited by the caller (complete_json / health)
        for round_ in range(2):
            # Hedged request: the first model starts; the others join if it is slow or fails; first valid reply wins.
            ms = model_list or models()
            tasks = [asyncio.create_task(try_model(ms[0]))]
            try:
                hedge_after = float(config.get("GEMMA_HEDGE_AFTER_S", "30"))
                done, _ = await asyncio.wait(tasks, timeout=hedge_after)
                if done and not tasks[0].exception():
                    text, model = tasks[0].result()
                    return text, model, stats["attempts"]
                # primary slow or failed: race the other models too (bounded extra load on the keys)
                tasks += [asyncio.create_task(try_model(m)) for m in ms[1:]]
                for fut in asyncio.as_completed([x for x in tasks if not (x.done() and x.exception())]):
                    try:
                        text, model = await fut
                        return text, model, stats["attempts"]
                    except GemmaUnavailable:
                        continue
            finally:
                for task in tasks:
                    _abandon(task)
            if not POOL.next_key(set()):
                break
            await asyncio.sleep(3)
    raise GemmaUnavailable(stats["last_err"])


XAI_POOL = KeyPool()


GROQ_POOL = KeyPool()

# OpenAI-compatible fallback providers: name -> (chat completions URL, keys env, model env, default model, key pool)
OPENAI_COMPAT = {
    "groq": ("https://api.groq.com/openai/v1/chat/completions", "GROQ_API_KEYS", "GROQ_MODEL", "openai/gpt-oss-120b",
             GROQ_POOL),
    "xai": ("https://api.x.ai/v1/chat/completions", "XAI_API_KEYS", "XAI_MODEL", "grok-3-mini", XAI_POOL),
}


def _provider_keys(name: str) -> list[str]:
    return [k for k in re.split(r"[,\s]+", config.get(OPENAI_COMPAT[name][1])) if k]


async def _openai_compat(name: str, prompt: str, temperature: float, max_tokens: int) -> tuple[str, str] | None:
    """Call an OpenAI-compatible fallback provider, rotating its keys. The answer is recorded as `<name>:<model>`."""
    url, _, model_env, default_model, pool = OPENAI_COMPAT[name]
    keys = _provider_keys(name)
    model = config.get(model_env, default_model)
    tried: set[str] = set()
    for _ in keys:
        key = next((k for k in keys if k not in tried and not pool._state.get(k, _KeyState()).dead
                    and pool._state.get(k, _KeyState()).cooldown_until <= time.time()), None)
        if not key:
            return None
        tried.add(key)
        try:
            r = await _http().post(url, headers={"Authorization": f"Bearer {key}"},
                                   json={"model": model, "temperature": temperature, "max_tokens": max_tokens,
                                         "messages": [{"role": "user", "content": prompt}]})
        except httpx.HTTPError:
            continue
        if r.status_code == 200:
            text = r.json()["choices"][0]["message"].get("content") or ""
            if text.strip():
                pool.succeeded(key)
                return text, f"{name}:{model}"
            continue
        msg = _err_msg(r) or r.text[:200]
        if r.status_code == 429:
            pool.rate_limited(key, msg)
        elif r.status_code >= 500:
            continue
        else:
            pool.retire(key, msg)  # credits exhausted / invalid key
    return None


async def _grok(prompt: str, temperature: float, max_tokens: int) -> tuple[str, str] | None:
    return await _openai_compat("xai", prompt, temperature, max_tokens)


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
    """Ask for JSON matching `schema` within a HARD `deadline_s`.

    Provider chain (each tier gets a time budget; a slow call is abandoned, never awaited):
      1. Gemma 4 (GEMMA_MODELS)                   primary, GEMMA_BUDGET_SHARE (default 60%) of the deadline
      2. Gemini fallback models (FALLBACK_MODELS)  only if Gemma failed or ran out of time
      3. xAI Grok (XAI_API_KEYS)                   last resort
    Every call is logged with the model that actually answered, so the capsule can disclose fallback use.
    Returns None if every tier fails; callers then use deterministic fallbacks (provenance "derived").

    Valid answers are cached by (prompt, schema) and reused for identical prompts (logged cached=true, disclosed in
    the capsule). GEMMA_CACHE=0 disables the cache."""
    key = hashlib.sha256(f"{schema.__name__}\n{prompt}".encode("utf-8")).hexdigest()
    cache_file = config.data_dir() / "_cache" / "gemma" / f"{key}.json"
    if config.get("GEMMA_CACHE", "1") != "0" and cache_file.exists():
        try:
            entry = json.loads(cache_file.read_text(encoding="utf-8"))
            obj = schema.model_validate(extract_json(entry["text"]))
            log_.record(purpose, entry["model"], 0, True, prompt, entry["text"], cached=True)
            return obj
        except (OSError, ValueError, ValidationError, KeyError):
            pass  # unreadable or stale entry: ask again
    async with _semaphore():
        result, text, model = await _complete_chain(log_, purpose, prompt, schema, max_tokens, deadline_s)
    if result is not None:
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps({"model": model, "text": text, "purpose": purpose,
                                              "created": time.strftime("%Y-%m-%dT%H:%M:%S")}), encoding="utf-8")
        except OSError:
            pass
    return result


async def _within(coro, timeout: float):
    """Run coro with a hard timeout; on timeout abandon it (do not wait for cancellation) and raise TimeoutError."""
    task = asyncio.ensure_future(coro)
    done, _ = await asyncio.wait({task}, timeout=max(0.0, timeout))
    if not done:
        _abandon(task)
        raise asyncio.TimeoutError
    return task.result()


async def _complete_chain(log_: CallLog, purpose: str, prompt: str, schema: type[T], max_tokens: int,
                          deadline_s: float) -> tuple[T | None, str, str]:
    t_end = time.time() + deadline_s
    gemma_share = float(config.get("GEMMA_BUDGET_SHARE", "0.6"))
    tiers = []
    if KeyPool.configured():
        tiers.append(("gemma", lambda q: generate(q, max_tokens=max_tokens), gemma_share))
        if fallback_models():
            tiers.append(("gemini", lambda q: generate(q, max_tokens=max_tokens, model_list=fallback_models()), 0.7))
    for name in ("groq", "xai"):
        if _provider_keys(name):
            tiers.append((name, (lambda n: lambda q: _compat_or_raise(n, q, max_tokens))(name), 0.85))
    if tiers and tiers[-1][2] != 1.0:  # the last tier may use all remaining time
        tiers[-1] = (tiers[-1][0], tiers[-1][1], 1.0)
    if not tiers:
        log_.record(purpose, "-", 0, False, prompt, "", "no API keys configured")
        return None, "", ""
    for name, call, share in tiers:
        tier_start = time.time()
        tier_end = tier_start + (t_end - tier_start) * share  # each tier leaves time for the ones after it
        current = prompt
        for attempt in range(2):  # one JSON-repair retry per tier
            remaining = tier_end - time.time()
            if remaining < 5:
                break
            t0 = time.time()
            try:
                text, model, n = await _within(call(current), remaining)
            except asyncio.TimeoutError:
                log_.record(purpose, name, int((time.time() - t0) * 1000), False, current, "",
                            f"{name}: no answer within {int(remaining)}s budget")
                break
            except GemmaUnavailable as e:
                log_.record(purpose, name, int((time.time() - t0) * 1000), False, current, "", str(e))
                break
            try:
                obj = schema.model_validate(extract_json(text))
                log_.record(purpose, model, int((time.time() - t0) * 1000), True, current, text, attempts=n)
                return obj, text, model
            except (ValueError, ValidationError) as e:
                err = str(e)[:600]
                log_.record(purpose, model, int((time.time() - t0) * 1000), False, current, text,
                            f"invalid JSON: {err}", attempts=n)
                current = (prompt + f"\n\nYour previous reply was invalid: {err}\n"
                           "Reply with ONLY the corrected JSON object, nothing else.")
    return None, "", ""


async def _compat_or_raise(name: str, prompt: str, max_tokens: int) -> tuple[str, str, int]:
    fb = await _openai_compat(name, prompt, 0.2, max_tokens)
    if not fb:
        raise GemmaUnavailable(f"{name}: no usable key (credits exhausted, rejected or rate-limited)")
    return fb[0], fb[1], 1


async def _grok_or_raise(prompt: str, max_tokens: int) -> tuple[str, str, int]:
    return await _compat_or_raise("xai", prompt, max_tokens)
