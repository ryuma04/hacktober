"""DepExit AI service — see docs/AI_SERVICE_CONTRACT.md. Every endpoint reads/writes stage files in job_dir."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import capsule, compare, config, gemma, materialize, propose, scan, state, usage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("depexit.ai")
app = FastAPI(title="DepExit AI service", version=config.TOOL_VERSION)
_health_cache: dict = {}


@app.exception_handler(HTTPException)
async def _http_err(_: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code,
                        content={"error": {"code": "bad_request" if exc.status_code == 400 else "internal",
                                           "message": str(exc.detail)}})


@app.exception_handler(Exception)
async def _any_err(_: Request, exc: Exception):
    log.exception("unhandled")
    return JSONResponse(status_code=500, content={"error": {"code": "internal", "message": f"{type(exc).__name__}: {exc}"}})


def _job(job_dir: str) -> Path:
    p = Path(job_dir).resolve()
    root = config.data_dir().resolve()
    if root not in p.parents and p != root:
        raise HTTPException(400, f"job_dir must be inside DATA_DIR ({root})")
    p.mkdir(parents=True, exist_ok=True)
    return p


def _repo(job: Path, repo_dir: str | None) -> Path:
    p = Path(repo_dir).resolve() if repo_dir else job / "repo"
    if not p.is_dir():
        raise HTTPException(400, f"repo_dir not found: {p}")
    return p


class JobReq(BaseModel):
    job_dir: str
    repo_dir: str | None = None
    python_version: str = "3.12"


class ProposeReq(JobReq):
    min_level: str = "medium"


class MaterializeReq(JobReq):
    out_repo_dir: str | None = None


class CompareReq(JobReq):
    run_ids: list[str] = ["baseline", "migrated"]


class CapsuleReq(JobReq):
    target: dict
    stage_errors: dict[str, str] = {}
    base_url: str


async def _probe_gemma() -> None:
    _health_cache["probing"] = True
    ok = False
    if gemma.configured():
        try:
            await gemma.generate("Reply with the word ok.", max_tokens=64)
            ok = True
            _health_cache.pop("error", None)
        except gemma.GemmaUnavailable as e:
            _health_cache["error"] = str(e)[:200]
    _health_cache["reachable"] = ok
    _health_cache["probing"] = False


@app.on_event("startup")
async def _startup() -> None:
    capsule.write_schema()
    asyncio.create_task(_probe_gemma())  # health answers instantly from the cached result


@app.get("/v1/health")
async def health(probe: bool = False):
    if probe:
        await _probe_gemma()
    elif "reachable" not in _health_cache and not _health_cache.get("probing"):
        asyncio.create_task(_probe_gemma())
    return {"status": "ok",
            "gemma": {"configured": gemma.configured(), "model": ",".join(gemma.models()),
                      "reachable": _health_cache.get("reachable", False), "probing": _health_cache.get("probing", False), "keys": gemma.POOL.status(),
                      "error": _health_cache.get("error")}}


@app.post("/v1/scan")
async def scan_ep(req: JobReq):
    job = _job(req.job_dir)
    log_ = gemma.CallLog(job)
    out = await scan.run(_repo(job, req.repo_dir), req.python_version, log_)
    state.write(job, "scan.json", out)
    return {**out, "ai_calls": log_.calls}


@app.post("/v1/usage")
async def usage_ep(req: JobReq):
    job = _job(req.job_dir)
    log_ = gemma.CallLog(job)
    out = await usage.run(_repo(job, req.repo_dir), state.read(job, "scan.json"), req.python_version, log_)
    state.write(job, "usage.json", out)
    return {"dependencies": len(out["usage"]), "extra_indicators": out["extra_indicators"], "ai_calls": log_.calls}


@app.post("/v1/propose")
async def propose_ep(req: ProposeReq):
    job = _job(req.job_dir)
    log_ = gemma.CallLog(job)
    out = await propose.run(job, req.python_version, req.min_level, log_)
    state.write(job, "proposals.json", out)
    return {**out, "ai_calls": log_.calls}


@app.post("/v1/materialize")
async def materialize_ep(req: MaterializeReq):
    job = _job(req.job_dir)
    log_ = gemma.CallLog(job)
    out_repo = Path(req.out_repo_dir).resolve() if req.out_repo_dir else job / "runs" / "migrated" / "repo"
    out = await materialize.run(job, _repo(job, req.repo_dir), out_repo, req.python_version, log_)
    state.write(job, "materialize.json", out)
    return {**out, "ai_calls": log_.calls}


@app.post("/v1/compare")
async def compare_ep(req: CompareReq):
    job = _job(req.job_dir)
    log_ = gemma.CallLog(job)
    out = await compare.run(job, req.run_ids, req.python_version, log_)
    state.write(job, "compare.json", out)
    return {"gaps": out["gaps"], "headline": out["headline"], "sandbox_indicators": out["sandbox_indicators"],
            "runs": [{k: r[k] for k in ("id", "status", "totals")} for r in out["runs"]], "ai_calls": log_.calls}


@app.post("/v1/capsule")
async def capsule_ep(req: CapsuleReq):
    job = _job(req.job_dir)
    return {**capsule.run(job, {**req.target, "python_version": req.python_version}, req.stage_errors, req.base_url),
            "ai_calls": []}
