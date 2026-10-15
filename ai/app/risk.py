"""Deterministic risk scoring (AI_SERVICE_CONTRACT.md §3)."""
from __future__ import annotations

POINTS = {
    "PY312_INCOMPATIBLE": 35, "YANKED": 25, "DEPRECATED_PACKAGE": 25, "DEPRECATED_API_USE": 20,
    "UNMAINTAINED": 20, "UNDECLARED": 20, "STDLIB_REPLACEMENT_AVAILABLE": 15, "MANIFEST_DRIFT": 15,
    "PRIVATE_API_USE": 15, "MONKEYPATCH": 15, "DECLARED_UNUSED": 10, "OUTDATED": 5, "UNPINNED": 5,
}
LEVELS = ["none", "low", "medium", "high", "critical"]


def indicator_points(ind: dict) -> int:
    code = ind["code"]
    if code == "KNOWN_VULNERABILITY":
        n = max(1, int(ind.get("count", 1)))
        return min(40, 30 + 5 * (n - 1))
    if code == "MAJOR_VERSIONS_BEHIND":
        return 20 if int(ind.get("majors", 1)) >= 2 else 15
    if code == "PY312_INCOMPATIBLE" and ind.get("severity") == "low":
        return 10
    return POINTS.get(code, 0)


def level_for(score: int) -> str:
    if score >= 70:
        return "critical"
    if score >= 45:
        return "high"
    if score >= 20:
        return "medium"
    if score > 0:
        return "low"
    return "none"


def score(indicators: list[dict]) -> tuple[int, str]:
    seen: dict[str, int] = {}
    for ind in indicators:  # one contribution per indicator code (the strongest)
        seen[ind["code"]] = max(seen.get(ind["code"], 0), indicator_points(ind))
    s = min(100, sum(seen.values()))
    return s, level_for(s)


def at_risk(level: str) -> bool:
    return LEVELS.index(level) >= LEVELS.index("medium")


def public_indicator(ind: dict) -> dict:
    """Strip internal scoring helpers before emitting."""
    return {k: v for k, v in ind.items() if k not in ("count", "majors")}
