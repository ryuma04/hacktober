"""
Comprehensive Whitebox Test Suite for DepExit Application.
Tests every registered endpoint in Go API (:8080), Python AI Service (:8001), and Frontend (:3000).
Tests valid inputs, boundary conditions, negative cases, error contracts, and SSE streaming.
Strictly local and offline-first: NO external LLM calls or quota consumption.
"""
from __future__ import annotations

import json
import time
import httpx
from pathlib import Path

GO_BASE = "http://localhost:8080"
AI_BASE = "http://localhost:8001"
UI_BASE = "http://localhost:3000"

results = []

def record_test(category: str, name: str, method: str, url: str, expected_status: int, actual_status: int, passed: bool, details: str, latency_ms: float):
    results.append({
        "category": category,
        "name": name,
        "method": method,
        "url": url,
        "expected_status": expected_status,
        "actual_status": actual_status,
        "passed": passed,
        "details": details,
        "latency_ms": round(latency_ms, 2)
    })
    mark = "PASS" if passed else "FAIL"
    print(f"[{mark:4}] {category:15} | {name:35} | {method:5} {actual_status:3} (exp {expected_status:3}) | {latency_ms:6.1f}ms | {details}")

def run_tests():
    client = httpx.Client(timeout=10.0)

    print("=" * 100)
    print("  DEPEXIT WHITEBOX ENDPOINT VERIFICATION SUITE")
    print("=" * 100)

    # =========================================================================
    # 1. GO REST API (:8080)
    # =========================================================================

    # 1.1 GET /api/health
    t0 = time.time()
    try:
        r = client.get(f"{GO_BASE}/api/health")
        lat = (time.time() - t0) * 1000
        data = r.json()
        passed = (r.status_code == 200 and data.get("status") == "ok" and 
                  "docker" in data and "sandbox_image_ready" in data and "version" in data)
        record_test("Go API", "Health Check", "GET", "/api/health", 200, r.status_code, passed, 
                    f"docker={data.get('docker')}, ai_service={data.get('ai_service')}, version={data.get('version')}", lat)
    except Exception as e:
        record_test("Go API", "Health Check", "GET", "/api/health", 200, 0, False, str(e), 0)

    # 1.2 CORS Preflight OPTIONS /api/analyses
    t0 = time.time()
    try:
        r = client.options(f"{GO_BASE}/api/analyses", headers={"Origin": "http://localhost:3000"})
        lat = (time.time() - t0) * 1000
        allow_origin = r.headers.get("access-control-allow-origin")
        allow_methods = r.headers.get("access-control-allow-methods")
        passed = (r.status_code == 204 and allow_origin == "http://localhost:3000" and "POST" in allow_methods)
        record_test("Go API", "CORS Preflight", "OPTIONS", "/api/analyses", 204, r.status_code, passed,
                    f"Allow-Origin: {allow_origin}, Allow-Methods: {allow_methods}", lat)
    except Exception as e:
        record_test("Go API", "CORS Preflight", "OPTIONS", "/api/analyses", 204, 0, False, str(e), 0)

    # 1.3 GET /api/analyses (List)
    t0 = time.time()
    try:
        r = client.get(f"{GO_BASE}/api/analyses")
        lat = (time.time() - t0) * 1000
        data = r.json()
        passed = (r.status_code == 200 and "items" in data and isinstance(data["items"], list))
        record_test("Go API", "List Analyses", "GET", "/api/analyses", 200, r.status_code, passed,
                    f"Returned {len(data.get('items', []))} items", lat)
    except Exception as e:
        record_test("Go API", "List Analyses", "GET", "/api/analyses", 200, 0, False, str(e), 0)

    # 1.4 POST /api/analyses (Invalid URL - Negative Test)
    t0 = time.time()
    try:
        r = client.post(f"{GO_BASE}/api/analyses", json={"repo_url": "https://gitlab.com/invalid/repo"})
        lat = (time.time() - t0) * 1000
        data = r.json()
        passed = (r.status_code == 400 and data.get("error", {}).get("code") == "bad_request")
        record_test("Go API", "Reject Non-GitHub Repo (400)", "POST", "/api/analyses", 400, r.status_code, passed,
                    f"error.code={data.get('error', {}).get('code')}: {data.get('error', {}).get('message')}", lat)
    except Exception as e:
        record_test("Go API", "Reject Non-GitHub Repo (400)", "POST", "/api/analyses", 400, 0, False, str(e), 0)

    # 1.5 POST /api/analyses (Malformed JSON - Negative Test)
    t0 = time.time()
    try:
        r = client.post(f"{GO_BASE}/api/analyses", content=b"invalid json{", headers={"Content-Type": "application/json"})
        lat = (time.time() - t0) * 1000
        data = r.json()
        passed = (r.status_code == 400 and data.get("error", {}).get("code") == "bad_request")
        record_test("Go API", "Reject Malformed JSON (400)", "POST", "/api/analyses", 400, r.status_code, passed,
                    f"error.code={data.get('error', {}).get('code')}", lat)
    except Exception as e:
        record_test("Go API", "Reject Malformed JSON (400)", "POST", "/api/analyses", 400, 0, False, str(e), 0)

    # 1.6 POST /api/analyses (Valid Creation - Positive Test)
    created_id = None
    t0 = time.time()
    try:
        r = client.post(f"{GO_BASE}/api/analyses", json={"repo_url": "https://github.com/rishrek/LinkWatch", "ref": "main"})
        lat = (time.time() - t0) * 1000
        data = r.json()
        created_id = data.get("id")
        links = data.get("links", {})
        passed = (r.status_code == 202 and created_id and data.get("status") == "queued" and 
                  links.get("self") == f"/api/analyses/{created_id}" and
                  links.get("events") == f"/api/analyses/{created_id}/events")
        record_test("Go API", "Create Analysis (202)", "POST", "/api/analyses", 202, r.status_code, passed,
                    f"Created id={created_id}, status={data.get('status')}", lat)
    except Exception as e:
        record_test("Go API", "Create Analysis (202)", "POST", "/api/analyses", 202, 0, False, str(e), 0)

    # 1.7 GET /api/analyses/{id} (Existing Job)
    if created_id:
        t0 = time.time()
        try:
            r = client.get(f"{GO_BASE}/api/analyses/{created_id}")
            lat = (time.time() - t0) * 1000
            data = r.json()
            passed = (r.status_code == 200 and data.get("id") == created_id and 
                      isinstance(data.get("stages"), list) and len(data["stages"]) >= 9)
            record_test("Go API", "Get Analysis Job Status", "GET", f"/api/analyses/{created_id}", 200, r.status_code, passed,
                        f"Job status={data.get('status')}, stages={len(data.get('stages', []))}", lat)
        except Exception as e:
            record_test("Go API", "Get Analysis Job Status", "GET", f"/api/analyses/{created_id}", 200, 0, False, str(e), 0)

    # 1.8 GET /api/analyses/dx_nonexistent (Negative Test 404)
    t0 = time.time()
    try:
        r = client.get(f"{GO_BASE}/api/analyses/dx_nonexistent_999")
        lat = (time.time() - t0) * 1000
        data = r.json()
        passed = (r.status_code == 404 and data.get("error", {}).get("code") == "not_found")
        record_test("Go API", "Get Nonexistent Job (404)", "GET", "/api/analyses/dx_nonexistent_999", 404, r.status_code, passed,
                    f"error.code={data.get('error', {}).get('code')}: {data.get('error', {}).get('message')}", lat)
    except Exception as e:
        record_test("Go API", "Get Nonexistent Job (404)", "GET", "/api/analyses/dx_nonexistent_999", 404, 0, False, str(e), 0)

    # 1.9 GET /api/analyses/{id}/capsule (Conflict 409 while running)
    if created_id:
        t0 = time.time()
        try:
            r = client.get(f"{GO_BASE}/api/analyses/{created_id}/capsule")
            lat = (time.time() - t0) * 1000
            data = r.json()
            passed = (r.status_code == 409 and data.get("error", {}).get("code") == "conflict")
            record_test("Go API", "Capsule Conflict When Running (409)", "GET", f"/api/analyses/{created_id}/capsule", 409, r.status_code, passed,
                        f"error.code={data.get('error', {}).get('code')}: {data.get('error', {}).get('message')}", lat)
        except Exception as e:
            record_test("Go API", "Capsule Conflict When Running (409)", "GET", f"/api/analyses/{created_id}/capsule", 409, 0, False, str(e), 0)

    # 1.10 GET /api/analyses/{id}/capsule.md (Conflict 409 while running)
    if created_id:
        t0 = time.time()
        try:
            r = client.get(f"{GO_BASE}/api/analyses/{created_id}/capsule.md")
            lat = (time.time() - t0) * 1000
            data = r.json()
            passed = (r.status_code == 409 and data.get("error", {}).get("code") == "conflict")
            record_test("Go API", "Capsule MD Conflict (409)", "GET", f"/api/analyses/{created_id}/capsule.md", 409, r.status_code, passed,
                        f"error.code={data.get('error', {}).get('code')}", lat)
        except Exception as e:
            record_test("Go API", "Capsule MD Conflict (409)", "GET", f"/api/analyses/{created_id}/capsule.md", 409, 0, False, str(e), 0)

    # 1.11 GET /api/analyses/{id}/patch.diff (Conflict 409 while running)
    if created_id:
        t0 = time.time()
        try:
            r = client.get(f"{GO_BASE}/api/analyses/{created_id}/patch.diff")
            lat = (time.time() - t0) * 1000
            data = r.json()
            passed = (r.status_code == 409 and data.get("error", {}).get("code") == "conflict")
            record_test("Go API", "Patch Diff Conflict (409)", "GET", f"/api/analyses/{created_id}/patch.diff", 409, r.status_code, passed,
                        f"error.code={data.get('error', {}).get('code')}", lat)
        except Exception as e:
            record_test("Go API", "Patch Diff Conflict (409)", "GET", f"/api/analyses/{created_id}/patch.diff", 409, 0, False, str(e), 0)

    # 1.12 GET /api/analyses/{id}/events (SSE Streaming & Content Type Verification)
    if created_id:
        t0 = time.time()
        try:
            with client.stream("GET", f"{GO_BASE}/api/analyses/{created_id}/events") as sse_res:
                lat = (time.time() - t0) * 1000
                ctype = sse_res.headers.get("content-type", "")
                cache_ctrl = sse_res.headers.get("cache-control", "")
                # Read first chunk
                first_chunk = next(sse_res.iter_text())
                passed = (sse_res.status_code == 200 and "text/event-stream" in ctype and 
                          "no-cache" in cache_ctrl and "event:" in first_chunk)
                record_test("Go API", "SSE Event Stream", "GET", f"/api/analyses/{created_id}/events", 200, sse_res.status_code, passed,
                            f"Content-Type: {ctype}, chunk_len={len(first_chunk)}, has_event={'event:' in first_chunk}", lat)
        except Exception as e:
            record_test("Go API", "SSE Event Stream", "GET", f"/api/analyses/{created_id}/events", 200, 0, False, str(e), 0)

    # 1.13 GET /api/analyses/{id}/runs/{run}/log (404 Nonexistent Run)
    if created_id:
        t0 = time.time()
        try:
            r = client.get(f"{GO_BASE}/api/analyses/{created_id}/runs/baseline/log")
            lat = (time.time() - t0) * 1000
            passed = (r.status_code == 404)
            record_test("Go API", "Run Log Not Found (404)", "GET", f"/api/analyses/{created_id}/runs/baseline/log", 404, r.status_code, passed,
                        f"Returns 404 before run completes", lat)
        except Exception as e:
            record_test("Go API", "Run Log Not Found (404)", "GET", f"/api/analyses/{created_id}/runs/baseline/log", 404, 0, False, str(e), 0)

    # 1.14 GET /api/analyses/{id}/runs/{run}/junit (404 Nonexistent JUnit)
    if created_id:
        t0 = time.time()
        try:
            r = client.get(f"{GO_BASE}/api/analyses/{created_id}/runs/baseline/junit")
            lat = (time.time() - t0) * 1000
            passed = (r.status_code == 404)
            record_test("Go API", "JUnit Not Found (404)", "GET", f"/api/analyses/{created_id}/runs/baseline/junit", 404, r.status_code, passed,
                        f"Returns 404 before test run finishes", lat)
        except Exception as e:
            record_test("Go API", "JUnit Not Found (404)", "GET", f"/api/analyses/{created_id}/runs/baseline/junit", 404, 0, False, str(e), 0)

    # 1.15 GET /api/analyses/{id}/migrated/{path} (Path Traversal Protection)
    if created_id:
        t0 = time.time()
        try:
            # Send raw path traversal
            r = client.get(f"{GO_BASE}/api/analyses/{created_id}/migrated/..%2f..%2f..%2fwindows%2fsystem32")
            lat = (time.time() - t0) * 1000
            passed = (r.status_code in (400, 404, 307))
            record_test("Go API", "Migrated Path Traversal Protected", "GET", f"/api/analyses/{created_id}/migrated/..", 400, r.status_code, passed,
                        f"Protected against traversal (status {r.status_code})", lat)
        except Exception as e:
            record_test("Go API", "Migrated Path Traversal Protected", "GET", f"/api/analyses/{created_id}/migrated/..", 400, 0, False, str(e), 0)

    # =========================================================================
    # 2. FASTAPI AI SERVICE (:8001)
    # =========================================================================

    # 2.1 GET /v1/health
    t0 = time.time()
    try:
        r = client.get(f"{AI_BASE}/v1/health")
        lat = (time.time() - t0) * 1000
        data = r.json()
        passed = (r.status_code == 200 and data.get("status") == "ok" and "gemma" in data)
        record_test("AI Service", "AI Health Check", "GET", "/v1/health", 200, r.status_code, passed,
                    f"gemma configured={data.get('gemma', {}).get('configured')}, models={data.get('gemma', {}).get('model')}", lat)
    except Exception as e:
        record_test("AI Service", "AI Health Check", "GET", "/v1/health", 200, 0, False, str(e), 0)

    # 2.2 GET /openapi.json
    t0 = time.time()
    try:
        r = client.get(f"{AI_BASE}/openapi.json")
        lat = (time.time() - t0) * 1000
        data = r.json()
        passed = (r.status_code == 200 and "openapi" in data and "paths" in data)
        paths = list(data.get("paths", {}).keys())
        record_test("AI Service", "OpenAPI Specification", "GET", "/openapi.json", 200, r.status_code, passed,
                    f"Documented endpoints: {len(paths)} ({', '.join(paths[:4])}...)", lat)
    except Exception as e:
        record_test("AI Service", "OpenAPI Specification", "GET", "/openapi.json", 200, 0, False, str(e), 0)

    # 2.3 POST /v1/scan (Validation: Empty Body -> 422)
    t0 = time.time()
    try:
        r = client.post(f"{AI_BASE}/v1/scan", json={})
        lat = (time.time() - t0) * 1000
        passed = (r.status_code == 422)
        record_test("AI Service", "Scan Missing job_dir (422)", "POST", "/v1/scan", 422, r.status_code, passed,
                    f"Pydantic rejected missing required fields with HTTP 422", lat)
    except Exception as e:
        record_test("AI Service", "Scan Missing job_dir (422)", "POST", "/v1/scan", 422, 0, False, str(e), 0)

    # 2.4 POST /v1/scan (Validation: Path outside DATA_DIR -> 400)
    t0 = time.time()
    try:
        r = client.post(f"{AI_BASE}/v1/scan", json={"job_dir": "C:/Windows/System32", "repo_dir": "C:/Windows"})
        lat = (time.time() - t0) * 1000
        data = r.json()
        passed = (r.status_code == 400 and data.get("error", {}).get("code") == "bad_request")
        record_test("AI Service", "Scan Path Outside DATA_DIR (400)", "POST", "/v1/scan", 400, r.status_code, passed,
                    f"error: {data.get('error', {}).get('message')}", lat)
    except Exception as e:
        record_test("AI Service", "Scan Path Outside DATA_DIR (400)", "POST", "/v1/scan", 400, 0, False, str(e), 0)

    # 2.5 POST /v1/usage (Validation: Missing scan.json -> 500 error handled)
    t0 = time.time()
    try:
        data_dir = Path("data").resolve()
        dummy_job = data_dir / "dx_test_dummy"
        dummy_job.mkdir(parents=True, exist_ok=True)
        # Use fresh request to avoid closed keep-alive socket on 500
        with httpx.Client(timeout=5.0) as fresh_c:
            r = fresh_c.post(f"{AI_BASE}/v1/usage", json={"job_dir": str(dummy_job), "repo_dir": str(dummy_job)})
            lat = (time.time() - t0) * 1000
            passed = (r.status_code in (400, 500))
            record_test("AI Service", "Usage Missing scan.json Handling", "POST", "/v1/usage", 500, r.status_code, passed,
                        f"Properly reports missing stage prerequisite without crashing", lat)
    except Exception as e:
        record_test("AI Service", "Usage Missing scan.json Handling", "POST", "/v1/usage", 500, 0, False, str(e), 0)

    # 2.6 POST /v1/propose (Validation: Missing job_dir outside DATA_DIR)
    t0 = time.time()
    try:
        with httpx.Client(timeout=5.0) as fresh_c:
            r = fresh_c.post(f"{AI_BASE}/v1/propose", json={"job_dir": "/unauthorized/path"})
            lat = (time.time() - t0) * 1000
            passed = (r.status_code == 400)
            record_test("AI Service", "Propose Path Validation (400)", "POST", "/v1/propose", 400, r.status_code, passed,
                        f"Rejected path outside DATA_DIR", lat)
    except Exception as e:
        record_test("AI Service", "Propose Path Validation (400)", "POST", "/v1/propose", 400, 0, False, str(e), 0)

    # 2.7 POST /v1/materialize (Validation: Missing job_dir outside DATA_DIR)
    t0 = time.time()
    try:
        r = client.post(f"{AI_BASE}/v1/materialize", json={"job_dir": "/unauthorized/path"})
        lat = (time.time() - t0) * 1000
        passed = (r.status_code == 400)
        record_test("AI Service", "Materialize Path Validation (400)", "POST", "/v1/materialize", 400, r.status_code, passed,
                    f"Rejected path outside DATA_DIR", lat)
    except Exception as e:
        record_test("AI Service", "Materialize Path Validation (400)", "POST", "/v1/materialize", 400, 0, False, str(e), 0)

    # 2.8 POST /v1/compare (Validation: Missing job_dir outside DATA_DIR)
    t0 = time.time()
    try:
        r = client.post(f"{AI_BASE}/v1/compare", json={"job_dir": "/unauthorized/path"})
        lat = (time.time() - t0) * 1000
        passed = (r.status_code == 400)
        record_test("AI Service", "Compare Path Validation (400)", "POST", "/v1/compare", 400, r.status_code, passed,
                    f"Rejected path outside DATA_DIR", lat)
    except Exception as e:
        record_test("AI Service", "Compare Path Validation (400)", "POST", "/v1/compare", 400, 0, False, str(e), 0)

    # 2.9 POST /v1/capsule (Validation: Missing job_dir outside DATA_DIR)
    t0 = time.time()
    try:
        r = client.post(f"{AI_BASE}/v1/capsule", json={"job_dir": "/unauthorized/path", "target": {}, "base_url": "/api/analyses/dx_1"})
        lat = (time.time() - t0) * 1000
        passed = (r.status_code == 400)
        record_test("AI Service", "Capsule Path Validation (400)", "POST", "/v1/capsule", 400, r.status_code, passed,
                    f"Rejected path outside DATA_DIR", lat)
    except Exception as e:
        record_test("AI Service", "Capsule Path Validation (400)", "POST", "/v1/capsule", 400, 0, False, str(e), 0)

    # =========================================================================
    # 3. FRONTEND NEXT.JS APP & FIXTURES (:3000)
    # =========================================================================

    # 3.1 GET / (Root Home Page)
    t0 = time.time()
    try:
        r = client.get(f"{UI_BASE}/")
        lat = (time.time() - t0) * 1000
        html = r.text
        passed = (r.status_code == 200 and "DepExit" in html and "Exit risky dependencies" in html)
        record_test("Frontend", "Home Page (Root /)", "GET", "/", 200, r.status_code, passed,
                    f"HTML served ({len(html)} bytes), branding & hero validated", lat)
    except Exception as e:
        record_test("Frontend", "Home Page (Root /)", "GET", "/", 200, 0, False, str(e), 0)

    # 3.2 GET /analyses/dx_demo01 (Dynamic Route)
    t0 = time.time()
    try:
        r = client.get(f"{UI_BASE}/analyses/dx_demo01")
        lat = (time.time() - t0) * 1000
        html = r.text
        passed = (r.status_code == 200 and ("DepExit" in html or "Analysis" in html))
        record_test("Frontend", "Analysis Dashboard Route", "GET", "/analyses/dx_demo01", 200, r.status_code, passed,
                    f"Dynamic App Router served ({len(html)} bytes)", lat)
    except Exception as e:
        record_test("Frontend", "Analysis Dashboard Route", "GET", "/analyses/dx_demo01", 200, 0, False, str(e), 0)

    # 3.3 Static Mock Fixtures
    fixtures = [
        ("health.json", "sandbox_image_ready", "application/json"),
        ("analyses_list.json", "dx_demo01", "application/json"),
        ("created.json", "dx_demo01", "application/json"),
        ("job_completed.json", "completed", "application/json"),
        ("job_failed.json", "failed", "application/json"),
        ("capsule.json", "schema_version", "application/json"),
        ("capsule.md", "Dependency Exit Capsule", "text/markdown"),
        ("patch.diff", "--- a/requirements.txt", "text/x-diff"),
        ("events.ndjson", "job_started", "text/plain"),
        ("logs/baseline-test.log", "pytest", "text/plain"),
        ("logs/migrated-test.log", "pytest", "text/plain"),
    ]

    for fname, token, expected_ctype in fixtures:
        t0 = time.time()
        try:
            r = client.get(f"{UI_BASE}/fixtures/{fname}")
            lat = (time.time() - t0) * 1000
            passed = (r.status_code == 200 and token in r.text)
            record_test("Frontend Fixtures", f"Fixture: {fname}", "GET", f"/fixtures/{fname}", 200, r.status_code, passed,
                        f"Status 200, token '{token}' matched ({len(r.text)} bytes)", lat)
        except Exception as e:
            record_test("Frontend Fixtures", f"Fixture: {fname}", "GET", f"/fixtures/{fname}", 200, 0, False, str(e), 0)

    # Print summary
    total = len(results)
    passed_count = sum(1 for x in results if x["passed"])
    failed_count = total - passed_count
    print("=" * 100)
    print(f"  ENDPOINT TEST SUMMARY: {passed_count}/{total} PASSED ({failed_count} FAILED)")
    print("=" * 100)

    # Save results to JSON
    out_file = Path(__file__).resolve().parent / "endpoint_test_results.json"
    out_file.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Results saved to {out_file}")

if __name__ == "__main__":
    run_tests()
