"""Comprehensive unit tests for AI service models, scoring, schema validation, and fallback mechanisms."""
import json
from pathlib import Path
import pytest
import jsonschema

from app import models, risk, compare, manifests, capsule
from app.gemma import GemmaUnavailable

REPO = Path(__file__).parent / "fixtures" / "minirepo"

def test_capsule_pydantic_schema_valid():
    """Verify that models.Capsule exports a valid JSON schema that can validate test capsules."""
    schema = models.Capsule.model_json_schema()
    assert schema["type"] == "object"
    assert "properties" in schema
    assert "schema_version" in schema["properties"]
    assert "capsule_id" in schema["properties"]
    assert "summary" in schema["properties"]
    assert "dependencies" in schema["properties"]

def test_capsule_fixture_validation():
    """Validate fixtures/capsule.json against the generated capsule JSON schema."""
    fixture_path = Path(__file__).resolve().parents[2] / "fixtures" / "capsule.json"
    assert fixture_path.exists(), "fixtures/capsule.json must exist"
    cap_data = json.loads(fixture_path.read_text(encoding="utf-8"))
    
    # Must validate cleanly via jsonschema against models.Capsule schema
    schema = models.Capsule.model_json_schema()
    jsonschema.validate(instance=cap_data, schema=schema)

def test_risk_scoring_matrix():
    """Test full scoring matrix according to AI_SERVICE_CONTRACT.md §3."""
    # 1. Known vulnerability (30 for first, +5 for second, max 40)
    inds = [{"code": "KNOWN_VULNERABILITY", "count": 1}]
    s, lvl = risk.score(inds)
    assert s == 30 and lvl == "medium"  # 30 is medium (20-44)

    # 45+ is high (e.g. KNOWN_VULNERABILITY + DEPRECATED_PACKAGE = 30 + 25 = 55)
    inds = [{"code": "KNOWN_VULNERABILITY", "count": 1}, {"code": "DEPRECATED_PACKAGE"}]
    s, lvl = risk.score(inds)
    assert s == 55 and lvl == "high"

    # Deprecated package alone: 25 pts -> medium
    inds = [{"code": "DEPRECATED_PACKAGE"}]
    s, lvl = risk.score(inds)
    assert s == 25 and lvl == "medium"

    # Manifest drift: 15 pts
    inds = [{"code": "MANIFEST_DRIFT"}]
    s, lvl = risk.score(inds)
    assert s == 15 and lvl == "low"

    # Undeclared: 20 pts
    inds = [{"code": "UNDECLARED"}]
    s, lvl = risk.score(inds)
    assert s == 20 and lvl == "medium"

    # Major versions behind (2 majors = 20 pts)
    inds = [{"code": "MAJOR_VERSIONS_BEHIND", "majors": 2}]
    s, lvl = risk.score(inds)
    assert s == 20 and lvl == "medium"

    # Capped at 100
    inds = [
        {"code": "KNOWN_VULNERABILITY", "count": 3}, # 40
        {"code": "PY312_INCOMPATIBLE", "severity": "critical"}, # 35
        {"code": "DEPRECATED_PACKAGE"}, # 25
        {"code": "MANIFEST_DRIFT"} # 15 -> sum 115 -> capped at 100
    ]
    s, lvl = risk.score(inds)
    assert s == 100 and lvl == "critical"

def test_compare_junit_xml_parsing(tmp_path):
    """Test JUnit XML parsing for passed, failed, and skipped tests."""
    xml_content = """<?xml version="1.0" encoding="utf-8"?>
    <testsuites>
      <testsuite name="pytest" errors="0" failures="1" skipped="1" tests="3" time="0.123">
        <testcase classname="tests.test_core" name="test_ok" time="0.010" />
        <testcase classname="tests.test_core" name="test_fail" time="0.020">
          <failure message="assertion error">Traceback ...</failure>
        </testcase>
        <testcase classname="tests.test_core" name="test_skip" time="0.000">
          <skipped message="skip for now" />
        </testcase>
      </testsuite>
    </testsuites>
    """
    junit_file = tmp_path / "junit.xml"
    junit_file.write_text(xml_content, encoding="utf-8")

    cases, totals = compare.parse_junit(junit_file)
    assert len(cases) == 3
    
    by_id = {c["id"]: c for c in cases}
    assert "tests/test_core.py::test_ok" in by_id
    assert by_id["tests/test_core.py::test_ok"]["outcome"] == "passed"
    
    assert "tests/test_core.py::test_fail" in by_id
    assert by_id["tests/test_core.py::test_fail"]["outcome"] == "failed"
    assert "assertion error" in by_id["tests/test_core.py::test_fail"]["message"]
    
    assert "tests/test_core.py::test_skip" in by_id
    assert by_id["tests/test_core.py::test_skip"]["outcome"] == "skipped"

def test_deterministic_fallback_when_gemma_offline(monkeypatch):
    """Verify that all AI-calling functions fall back gracefully when Gemma is unavailable."""
    from app import gemma, prompts

    async def mock_offline(*args, **kwargs):
        raise GemmaUnavailable("Simulated quota exhaustion or offline mode")

    monkeypatch.setattr(gemma, "generate", mock_offline)
    monkeypatch.setattr(gemma, "_grok_or_raise", mock_offline)  # every tier of the provider chain is offline
    monkeypatch.setenv("GEMMA_CACHE", "0")

    # Calling complete_json should return None and log one failed call per provider tier tried
    log_ = gemma.CallLog(None)
    import asyncio
    res = asyncio.run(gemma.complete_json(log_, "test_purpose", "prompt text", prompts.ItemsReply))
    assert res is None
    assert len(log_.calls) >= 1
    assert all(c["ok"] is False for c in log_.calls)
    assert "Simulated quota exhaustion" in log_.calls[0]["error"]
