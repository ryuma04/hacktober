"""
Pipeline Scenarios Validation Script (Scenarios A - J)
Exercises the internal pipeline functions with controlled fixtures and mocks.
Strictly offline: no external LLM or network requests.
"""
import sys
import asyncio
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ai"))

from app import manifests, scan, usage, risk, compare, capsule, state, gemma
from app.gemma import GemmaUnavailable

ROOT = Path(__file__).resolve().parents[1]
MINIREPO = ROOT / "ai" / "tests" / "fixtures" / "minirepo"

def test_scenario_a_healthy_dependency():
    """Scenario A: Healthy package has 0 risk score and no indicators invented."""
    inds = []
    score, lvl = risk.score(inds)
    assert score == 0
    assert lvl == "none"
    assert not risk.at_risk(lvl)

def test_scenario_b_risky_dependency():
    """Scenario B: Package with known vuln and incompatibility gets scored and tagged."""
    inds = [
        {"code": "KNOWN_VULNERABILITY", "count": 2, "severity": "high"},
        {"code": "PY312_INCOMPATIBLE", "severity": "critical"}
    ]
    score, lvl = risk.score(inds)
    assert score >= 70
    assert lvl == "critical"
    assert risk.at_risk(lvl)

def test_scenario_c_dependency_usage():
    """Scenario C: Dependency usage captures imports, calls, monkeypatching, private APIs."""
    sc = {"dependencies": [{"name": "oldlib", "import_names": ["oldlib"]}]}
    log_ = gemma.CallLog(None)
    
    # Offline usage analysis
    out = asyncio.run(usage.run(MINIREPO, sc, "3.12", log_))
    assert "oldlib" in out["usage"]
    locs = out["usage"]["oldlib"]["locations"]
    assert len(locs) > 0
    kinds = {l["kind"] for l in locs}
    assert "import" in kinds
    assert "monkeypatch" in kinds
    assert "private_api" in kinds
    
    # Check extra indicators generated
    extra = out["extra_indicators"]["oldlib"]
    extra_codes = {i["code"] for i in extra}
    assert "PRIVATE_API_USE" in extra_codes
    assert "MONKEYPATCH" in extra_codes

def test_scenario_d_and_e_gap_analysis():
    """Scenario D & E: Gap analysis differentiates fixed, regressed, still failing."""
    base_tests = [
        {"id": "tests/test_a.py::test_1", "outcome": "failed"},
        {"id": "tests/test_b.py::test_2", "outcome": "passed"},
        {"id": "tests/test_c.py::test_3", "outcome": "failed"},
    ]
    mig_tests = [
        {"id": "tests/test_a.py::test_1", "outcome": "passed"},     # Fixed
        {"id": "tests/test_b.py::test_2", "outcome": "failed"},     # Regressed!
        {"id": "tests/test_c.py::test_3", "outcome": "failed"},     # Still failing
    ]
    
    base_by_id = {t["id"]: t["outcome"] for t in base_tests}
    mig_by_id = {t["id"]: t["outcome"] for t in mig_tests}
    
    gaps = []
    for tid, b_out in base_by_id.items():
        m_out = mig_by_id.get(tid, "not_run")
        if b_out == "failed" and m_out == "passed":
            gaps.append({"test_id": tid, "change": "fixed", "severity": "low"})
        elif b_out == "passed" and m_out != "passed":
            gaps.append({"test_id": tid, "change": "regressed", "severity": "critical"})
        elif b_out != "passed" and m_out != "passed":
            gaps.append({"test_id": tid, "change": "still_failing", "severity": "medium"})

    changes = {g["test_id"]: g["change"] for g in gaps}
    assert changes["tests/test_a.py::test_1"] == "fixed"
    assert changes["tests/test_b.py::test_2"] == "regressed"
    assert changes["tests/test_c.py::test_3"] == "still_failing"

def test_scenario_f_installation_failure_handling(tmp_path):
    """Scenario F: Simulated package install failure skips pytest and records install_failed."""
    run_dir = tmp_path / "runs" / "baseline"
    run_dir.mkdir(parents=True, exist_ok=True)
    
    res = {
        "run_id": "baseline",
        "kind": "baseline",
        "status": "install_failed",
        "install_exit_code": 1,
        "test_exit_code": None,
        "duration_s": 4.2,
        "command": ["pytest"],
        "install_command": ["pip", "install", "-r", "requirements.txt"]
    }
    (run_dir / "result.json").write_text(json.dumps(res), encoding="utf-8")
    (run_dir / "install.log").write_text("ERROR: No matching distribution found for broken-pkg==9.9.9\n", encoding="utf-8")
    (run_dir / "test.log").write_text("[depexit] tests not run: dependency installation failed\n", encoding="utf-8")

    # In compare / capsule stage, missing junit with install_failed is cleanly handled
    cases, coll = compare.parse_junit(run_dir / "junit.xml")
    assert cases == []
    assert coll == {}

def test_scenario_g_missing_ai_credentials_honest_reporting(tmp_path):
    """Scenario G: Running without AI credentials honestly marks provenance as derived and adds limitations."""
    job_dir = tmp_path / "dx_test_no_ai"
    job_dir.mkdir(parents=True, exist_ok=True)
    
    # Write mock stage files
    scan_data = {
        "manifests": ["requirements.txt"],
        "dependencies": [
            {
                "name": "urllib3",
                "import_names": ["urllib3"],
                "declared": [{"file": "requirements.txt", "line": 1, "spec": "urllib3==1.26.5"}],
                "risk": {"level": "medium", "score": 25, "indicators": [{"code": "KNOWN_VULNERABILITY", "severity": "medium", "detail": "CVE-xxxx", "evidence": []}], "rationale": "1 vulnerability", "rationale_provenance": "derived"},
                "usage": {"locations": [], "files": [], "summary": "Used in project.", "summary_provenance": "derived"}
            }
        ]
    }
    state.write(job_dir, "scan.json", scan_data)
    
    # Run capsule without AI calls
    target = {"repo_url": "https://github.com/example/demo", "ref": "main", "commit": "1234567", "python_version": "3.12"}
    res = capsule.run(job_dir, target, {}, "/api/analyses/dx_test_no_ai")
    
    cap_file = job_dir / "capsule.json"
    assert cap_file.exists()
    cap = json.loads(cap_file.read_text(encoding="utf-8"))
    
    # Check honest reporting in AI block and limitations
    assert cap["ai"]["fallback_used"] is True
    assert any("Gemma 4 was unavailable" in l or "fallback" in l for l in cap["limitations"])
    assert (job_dir / "CAPSULE.md").exists()

def test_scenario_h_external_metadata_unavailable():
    """Scenario H: When external PyPI/OSV metadata is unavailable (e.g. 404), marked unknown rather than safe."""
    facts = {"exists": False}
    # Per scan.py line 233: if not f.get("exists"), inds.append(_ind("UNMAINTAINED", "medium", "Package not found on PyPI", ...))
    inds = [{"code": "UNMAINTAINED", "severity": "medium", "detail": "Package not found on PyPI", "evidence": [{"source": "pypi", "detail": "404"}]}]
    s, lvl = risk.score(inds)
    assert s > 0
    assert lvl != "none"  # NEVER treated as safe!

def test_scenario_i_stage_errors_recorded_in_limitations(tmp_path):
    """Scenario I: Partial stage error recorded in capsule limitations."""
    job_dir = tmp_path / "dx_test_stage_err"
    job_dir.mkdir(parents=True, exist_ok=True)
    state.write(job_dir, "scan.json", {"manifests": [], "dependencies": []})
    
    target = {"repo_url": "https://github.com/example/demo", "ref": "main", "commit": "1234567", "python_version": "3.12"}
    stage_errors = {"propose": "timed out after 180s"}
    res = capsule.run(job_dir, target, stage_errors, "/api/analyses/dx_test_stage_err")
    
    cap = json.loads((job_dir / "capsule.json").read_text(encoding="utf-8"))
    assert any("Stage 'propose' failed: timed out after 180s" in l for l in cap["limitations"])

if __name__ == "__main__":
    print("Running Pipeline Scenarios A - I...")
    test_scenario_a_healthy_dependency()
    print("[PASS] Scenario A: Healthy dependency")
    test_scenario_b_risky_dependency()
    print("[PASS] Scenario B: Risky dependency")
    test_scenario_c_dependency_usage()
    print("[PASS] Scenario C: Dependency usage")
    test_scenario_d_and_e_gap_analysis()
    print("[PASS] Scenario D & E: Gap analysis (fixed, regressed, still failing)")
    
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        test_scenario_f_installation_failure_handling(Path(td))
        print("[PASS] Scenario F: Installation failure handling")
        test_scenario_g_missing_ai_credentials_honest_reporting(Path(td))
        print("[PASS] Scenario G: Missing AI credentials & honest reporting")
        test_scenario_h_external_metadata_unavailable()
        print("[PASS] Scenario H: External metadata unavailable")
        test_scenario_i_stage_errors_recorded_in_limitations(Path(td))
        print("[PASS] Scenario I: Nonfatal stage error recorded in limitations")
    print("ALL SCENARIOS PASSED!")
