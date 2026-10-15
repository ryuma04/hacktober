"""PyPI and OSV lookups with an on-disk cache (per day) so repeated runs are fast and reproducible."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from pathlib import Path

import httpx

from . import config

log = logging.getLogger("depexit.registry")
_client: httpx.AsyncClient | None = None
_sem = asyncio.Semaphore(8)


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(20.0), headers={"User-Agent": "DepExit/0.1"})
    return _client


def _cache_path(kind: str, key: str) -> Path:
    day = time.strftime("%Y%m%d")
    h = hashlib.sha1(key.encode()).hexdigest()[:16]
    p = config.data_dir() / "_cache" / kind / day
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{h}.json"


async def _cached(kind: str, key: str, fetch):
    path = _cache_path(kind, key)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    async with _sem:
        data = await fetch()
    if data is not None:
        path.write_text(json.dumps(data), encoding="utf-8")
    return data


async def pypi_project(name: str) -> dict | None:
    async def fetch():
        try:
            r = await client().get(f"{config.PYPI_URL}/{name}/json")
        except httpx.HTTPError as e:
            log.warning("pypi %s: %s", name, e)
            return None
        return r.json() if r.status_code == 200 else {"_status": r.status_code}
    d = await _cached("pypi", name, fetch)
    return None if not d or "_status" in d else d


async def pypi_release(name: str, version: str) -> dict | None:
    async def fetch():
        try:
            r = await client().get(f"{config.PYPI_URL}/{name}/{version}/json")
        except httpx.HTTPError as e:
            log.warning("pypi %s==%s: %s", name, version, e)
            return None
        return r.json() if r.status_code == 200 else {"_status": r.status_code}
    d = await _cached("pypi", f"{name}=={version}", fetch)
    return None if not d or "_status" in d else d


async def osv_query(name: str, version: str, ecosystem: str = "PyPI") -> list[dict] | None:
    async def fetch():
        try:
            r = await client().post(config.OSV_URL, json={"package": {"name": name, "ecosystem": ecosystem}, "version": version})
        except httpx.HTTPError as e:
            log.warning("osv %s==%s: %s", name, version, e)
            return None
        if r.status_code != 200:
            return None
        return {"vulns": r.json().get("vulns", [])}
    key = f"{name}=={version}" if ecosystem == "PyPI" else f"{ecosystem}:{name}=={version}"
    d = await _cached("osv", key, fetch)
    return None if d is None else d["vulns"]


def release_date(project: dict, version: str) -> str | None:
    files = (project.get("releases") or {}).get(version) or []
    times = sorted(f.get("upload_time_iso_8601") or f.get("upload_time") for f in files if f.get("upload_time"))
    return times[0][:10] if times else None


NPM_REGISTRY = "https://registry.npmjs.org"


async def npm_package(name: str, version: str | None = None) -> dict | None:
    """npm registry facts for a package, reduced to what DepExit needs (full documents can be megabytes)."""
    async def fetch():
        url = f"{NPM_REGISTRY}/{name.replace('/', '%2F')}"
        try:
            r = await client().get(url, timeout=httpx.Timeout(30.0))
        except httpx.HTTPError as e:
            log.warning("npm %s: %s", name, e)
            return None
        if r.status_code != 200:
            return {"_status": r.status_code}
        doc = r.json()
        latest = (doc.get("dist-tags") or {}).get("latest")
        versions = doc.get("versions") or {}
        times = doc.get("time") or {}
        lv = versions.get(latest) or {}
        repo = doc.get("repository") or lv.get("repository") or {}
        return {
            "latest": latest,
            "latest_time": times.get(latest),
            "modified": times.get("modified"),
            "deprecated_latest": lv.get("deprecated"),
            "homepage": doc.get("homepage") or lv.get("homepage") or (repo.get("url") if isinstance(repo, dict) else None),
            "description": (doc.get("description") or "")[:200],
            "engines_latest": lv.get("engines"),
            # per-version facts we may need for the installed version
            "versions": {v: {"time": times.get(v), "deprecated": (versions[v] or {}).get("deprecated"),
                             "dependencies": sorted(((versions[v] or {}).get("dependencies") or {}).keys()),
                             "peers": sorted(((versions[v] or {}).get("peerDependencies") or {}).keys())}
                         for v in versions},
        }
    d = await _cached("npm2", name, fetch)  # npm2: reduced document incl. peer dependencies
    if d and d.get("_status") == 404:
        return {"_missing": True}  # really not on the registry
    return None if not d or "_status" in d else d  # None = lookup failed (network); never cached
