package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func newTestAPI(t *testing.T) (*API, *Store, string) {
	tmpDir := t.TempDir()
	store := NewStore(tmpDir)
	cfg := Config{
		Port:           "8080",
		DataDir:        tmpDir,
		AIServiceURL:   "http://localhost:8001",
		AllowedOrigins: []string{"http://localhost:3000"},
		SandboxImage:   "python:3.12-slim",
		DefaultRepoURL: "https://github.com/rishrek/LinkWatch",
	}
	pipe := &Pipeline{cfg: cfg, store: store, ai: NewAIClient(cfg.AIServiceURL), sb: &Sandbox{}}
	return &API{cfg: cfg, store: store, pipe: pipe, runJob: func(id string) {}}, store, tmpDir
}

func TestHealthEndpoint(t *testing.T) {
	api, _, _ := newTestAPI(t)
	req := httptest.NewRequest(http.MethodGet, "/api/health", nil)
	rec := httptest.NewRecorder()

	api.routes().ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}

	var res map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &res); err != nil {
		t.Fatalf("invalid json response: %v", err)
	}
	if res["status"] != "ok" {
		t.Fatalf("expected status ok, got %v", res["status"])
	}
	if res["version"] != "0.1.0" {
		t.Fatalf("expected version 0.1.0, got %v", res["version"])
	}
}

func TestCreateAnalysisValidation(t *testing.T) {
	api, _, _ := newTestAPI(t)

	// Test 1: Invalid repo URL scheme/domain
	body := `{"repo_url": "https://gitlab.com/invalid/repo"}`
	req := httptest.NewRequest(http.MethodPost, "/api/analyses", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	api.routes().ServeHTTP(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 for non-github repo, got %d", rec.Code)
	}
	var errRes map[string]map[string]string
	_ = json.Unmarshal(rec.Body.Bytes(), &errRes)
	if errRes["error"]["code"] != "bad_request" {
		t.Fatalf("expected error code bad_request, got %s", errRes["error"]["code"])
	}

	// Test 2: Malformed JSON
	req = httptest.NewRequest(http.MethodPost, "/api/analyses", strings.NewReader(`{invalid json`))
	req.Header.Set("Content-Type", "application/json")
	rec = httptest.NewRecorder()
	api.routes().ServeHTTP(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 for malformed json, got %d", rec.Code)
	}

	// Test 3: Valid repo URL
	body = `{"repo_url": "https://github.com/rishrek/LinkWatch", "ref": "main"}`
	req = httptest.NewRequest(http.MethodPost, "/api/analyses", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rec = httptest.NewRecorder()
	api.routes().ServeHTTP(rec, req)

	if rec.Code != http.StatusAccepted {
		t.Fatalf("expected 202 for valid repo, got %d", rec.Code)
	}
	var createdRes map[string]any
	_ = json.Unmarshal(rec.Body.Bytes(), &createdRes)
	if createdRes["status"] != "queued" {
		t.Fatalf("expected queued status, got %v", createdRes["status"])
	}
	if !strings.HasPrefix(createdRes["id"].(string), "dx_") {
		t.Fatalf("expected dx_ prefix for id, got %v", createdRes["id"])
	}
}

func TestGetAnalysisNotFound(t *testing.T) {
	api, _, _ := newTestAPI(t)
	req := httptest.NewRequest(http.MethodGet, "/api/analyses/dx_nonexistent", nil)
	rec := httptest.NewRecorder()
	api.routes().ServeHTTP(rec, req)

	if rec.Code != http.StatusNotFound {
		t.Fatalf("expected 404, got %d", rec.Code)
	}
}

func TestArtifactConflictWhileRunning(t *testing.T) {
	api, store, _ := newTestAPI(t)
	job := store.Create("https://github.com/rishrek/LinkWatch", "main", Options{})
	// Job is in status "queued"
	req := httptest.NewRequest(http.MethodGet, "/api/analyses/"+job.ID+"/capsule", nil)
	rec := httptest.NewRecorder()
	api.routes().ServeHTTP(rec, req)

	if rec.Code != http.StatusConflict {
		t.Fatalf("expected 409 Conflict while job not finished, got %d", rec.Code)
	}
	var errRes map[string]map[string]string
	_ = json.Unmarshal(rec.Body.Bytes(), &errRes)
	if errRes["error"]["code"] != "conflict" {
		t.Fatalf("expected error code conflict, got %s", errRes["error"]["code"])
	}
}

func TestMigratedFilePathTraversal(t *testing.T) {
	api, store, dataDir := newTestAPI(t)
	job := store.Create("https://github.com/rishrek/LinkWatch", "main", Options{})

	// Create dummy migrated repo directory
	migratedDir := filepath.Join(dataDir, job.ID, "runs", "migrated", "repo")
	_ = os.MkdirAll(migratedDir, 0o755)
	_ = os.WriteFile(filepath.Join(migratedDir, "safe.txt"), []byte("safe content"), 0o644)

	// Attempt path traversal
	req := httptest.NewRequest(http.MethodGet, "/api/analyses/"+job.ID+"/migrated/../../secret.txt", nil)
	rec := httptest.NewRecorder()
	api.routes().ServeHTTP(rec, req)

	// Must reject with 400 bad_request, 404, or 307 (ServeMux path clean redirect)
	if rec.Code != http.StatusBadRequest && rec.Code != http.StatusNotFound && rec.Code != http.StatusTemporaryRedirect {
		t.Fatalf("expected 400, 404, or 307 for path traversal attempt, got %d", rec.Code)
	}

	// Safe file should succeed
	req = httptest.NewRequest(http.MethodGet, "/api/analyses/"+job.ID+"/migrated/safe.txt", nil)
	rec = httptest.NewRecorder()
	api.routes().ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200 for safe file, got %d", rec.Code)
	}
	if strings.TrimSpace(rec.Body.String()) != "safe content" {
		t.Fatalf("unexpected content: %s", rec.Body.String())
	}
}

func TestCORSHeaders(t *testing.T) {
	api, _, _ := newTestAPI(t)

	// Preflight OPTIONS
	req := httptest.NewRequest(http.MethodOptions, "/api/analyses", nil)
	req.Header.Set("Origin", "http://localhost:3000")
	rec := httptest.NewRecorder()
	api.routes().ServeHTTP(rec, req)

	if rec.Code != http.StatusNoContent {
		t.Fatalf("expected 204 No Content for preflight, got %d", rec.Code)
	}
	if rec.Header().Get("Access-Control-Allow-Origin") != "http://localhost:3000" {
		t.Fatalf("expected CORS allow origin header, got %s", rec.Header().Get("Access-Control-Allow-Origin"))
	}
}
