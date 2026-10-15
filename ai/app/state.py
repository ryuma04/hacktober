"""Read/write stage files in a job directory and merge indicators from later stages."""
from __future__ import annotations

import json
from pathlib import Path

from . import risk


def read(job_dir: Path, name: str, default=None):
    p = job_dir / name
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def write(job_dir: Path, name: str, data) -> None:
    p = job_dir / name
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def merged_dependencies(job_dir: Path) -> list[dict]:
    """scan.json deps + usage extra indicators + sandbox indicators, rescored. Returns deep copies."""
    scan = read(job_dir, "scan.json", {"dependencies": []})
    usage = read(job_dir, "usage.json", {"extra_indicators": {}})
    compare = read(job_dir, "compare.json", {}) or {}
    deps = json.loads(json.dumps(scan["dependencies"]))
    for d in deps:
        inds = d["risk"]["indicators"]
        for src in (usage.get("extra_indicators", {}), compare.get("sandbox_indicators", {})):
            for ind in src.get(d["name"], []):
                existing = next((i for i in inds if i["code"] == ind["code"]), None)
                if existing and existing.get("severity") == "low" and ind.get("severity") != "low":
                    inds.remove(existing)  # stronger evidence replaces the weak metadata signal
                    existing = None
                if existing:
                    existing["evidence"].extend(e for e in ind["evidence"] if e not in existing["evidence"])
                else:
                    inds.append(ind)
        d["risk"]["score"], d["risk"]["level"] = risk.score(inds)
        d["usage"] = (usage.get("usage") or {}).get(d["name"], {"locations": [], "files": [], "summary": "",
                                                                 "summary_provenance": "derived"})
    deps.sort(key=lambda d: -d["risk"]["score"])
    return deps
