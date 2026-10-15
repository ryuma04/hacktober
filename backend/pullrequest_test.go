package main

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

const testToken = "ghp_test_secret_token_value"

// fakeGitHub records calls and plays a repo the token cannot push to (forces the fork path).
type fakeGitHub struct {
	mu      sync.Mutex
	calls   []string
	parents []string // parent of each created commit, in order
	prBody  map[string]any
	authOK  bool
}

func (f *fakeGitHub) handler(t *testing.T) http.Handler {
	commitN := 0
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		f.mu.Lock()
		defer f.mu.Unlock()
		f.calls = append(f.calls, r.Method+" "+r.URL.Path)
		if r.Header.Get("Authorization") != "Bearer "+testToken {
			w.WriteHeader(401)
			_, _ = io.WriteString(w, `{"message":"Bad credentials"}`)
			return
		}
		f.authOK = true
		var body map[string]any
		_ = json.NewDecoder(r.Body).Decode(&body)
		j := func(v any) { _ = json.NewEncoder(w).Encode(v) }
		switch {
		case r.URL.Path == "/user":
			j(map[string]any{"login": "alice"})
		case r.Method == "GET" && r.URL.Path == "/repos/up/proj":
			j(map[string]any{"default_branch": "main", "permissions": map[string]any{"push": false}})
		case r.Method == "POST" && r.URL.Path == "/repos/up/proj/forks":
			w.WriteHeader(202)
			j(map[string]any{"full_name": "alice/proj", "owner": map[string]any{"login": "alice"}})
		case r.Method == "GET" && strings.HasPrefix(r.URL.Path, "/repos/alice/proj/git/commits/"):
			j(map[string]any{"tree": map[string]any{"sha": "basetree"}})
		case r.Method == "POST" && r.URL.Path == "/repos/alice/proj/git/blobs":
			j(map[string]any{"sha": "blob1"})
		case r.Method == "POST" && r.URL.Path == "/repos/alice/proj/git/trees":
			j(map[string]any{"sha": "tree1"})
		case r.Method == "POST" && r.URL.Path == "/repos/alice/proj/git/commits":
			commitN++
			ps, _ := body["parents"].([]any)
			f.parents = append(f.parents, ps[0].(string))
			j(map[string]any{"sha": "c" + string(rune('0'+commitN))})
		case r.Method == "POST" && r.URL.Path == "/repos/alice/proj/git/refs":
			w.WriteHeader(201)
			j(map[string]any{})
		case r.Method == "POST" && r.URL.Path == "/repos/up/proj/pulls":
			f.prBody = body
			w.WriteHeader(201)
			j(map[string]any{"html_url": "https://github.com/up/proj/pull/7", "number": 7})
		default:
			t.Errorf("unexpected call %s %s", r.Method, r.URL.Path)
			w.WriteHeader(404)
		}
	})
}

func writeFile(t *testing.T, path, content string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}

func setupPRJob(t *testing.T) (*API, string) {
	t.Helper()
	store := NewStore(t.TempDir())
	job := store.Create("https://github.com/up/proj", "main", Options{})
	store.Update(job.ID, func(j *Job) { j.Status, j.Commit = "completed", "abc123def4567890" })
	dir := store.jobDir(job.ID)
	writeFile(t, filepath.Join(dir, "repo", "requirements.txt"), "toml==0.10.2\n")
	writeFile(t, filepath.Join(dir, "repo", "app", "config.py"), "import toml\n")
	writeFile(t, filepath.Join(dir, "repo", "README.md"), "same\n")
	writeFile(t, filepath.Join(dir, "runs", "migrated", "repo", "requirements.txt"), "")
	writeFile(t, filepath.Join(dir, "runs", "migrated", "repo", "app", "config.py"), "import tomllib\n")
	writeFile(t, filepath.Join(dir, "runs", "migrated", "repo", "README.md"), "same\n")
	writeFile(t, filepath.Join(dir, "capsule.json"), `{
	  "summary": {"verdict": "safe_to_migrate", "headline": "All good", "at_risk": 1, "dependencies_total": 1,
	              "baseline": {"passed": 1, "total": 2}, "migrated": {"passed": 2, "total": 2, "status": "passed"},
	              "gaps": {"fixed": 1, "regressed": 0, "still_failing": 0}},
	  "ai": {"provider": "Google AI Studio (Gemini API)", "models_used": {"gemma-4-26b-a4b-it": 3}},
	  "dependencies": [{"name": "toml", "pinned_version": "0.10.2", "latest_version": "0.10.2",
	    "risk": {"level": "critical", "score": 70, "indicators": [{"code": "DEPRECATED_PACKAGE"}]},
	    "replacement": {"strategy": "stdlib", "package": "tomllib", "model": "gemma-4-26b-a4b-it"},
	    "migration": {"applied": true, "files_changed": ["app/config.py", "requirements.txt"]},
	    "compatibility_gaps": []}],
	  "limitations": ["Verified only as far as the tests reach."]
	}`)
	return &API{store: store}, job.ID
}

func call(t *testing.T, api *API, method, id, body string) (*httptest.ResponseRecorder, map[string]any) {
	t.Helper()
	mux := http.NewServeMux()
	mux.HandleFunc("POST /api/analyses/{id}/pull-request", api.pullRequest)
	mux.HandleFunc("GET /api/analyses/{id}/pull-request", api.pullRequest)
	req := httptest.NewRequest(method, "/api/analyses/"+id+"/pull-request", strings.NewReader(body))
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)
	var out map[string]any
	_ = json.Unmarshal(rec.Body.Bytes(), &out)
	return rec, out
}

func TestPullRequestDryRunPlan(t *testing.T) {
	api, id := setupPRJob(t)
	rec, out := call(t, api, "POST", id, `{"dry_run": true}`)
	if rec.Code != 200 {
		t.Fatalf("dry run: %d %s", rec.Code, rec.Body.String())
	}
	plan := out["plan"].(map[string]any)
	files := plan["files_changed"].([]any)
	if len(files) != 2 || files[0] != "app/config.py" || files[1] != "requirements.txt" {
		t.Fatalf("files_changed = %v (README is unchanged and must be excluded)", files)
	}
	if plan["base_commit"] != "abc123def4567890" || plan["branch"] != "depexit/migrate-"+id {
		t.Fatalf("unexpected base/branch: %v %v", plan["base_commit"], plan["branch"])
	}
	body := plan["body"].(string)
	for _, want := range []string{"safe_to_migrate", "1 / 2", "2 / 2", "`toml`", "stdlib tomllib", "gemma-4-26b-a4b-it", "Limitations"} {
		if !strings.Contains(body, want) {
			t.Errorf("PR body missing %q", want)
		}
	}
	if commits := plan["commits"].([]any); len(commits) != 2 ||
		!strings.Contains(commits[0].(map[string]any)["message"].(string), "for toml migration") {
		t.Fatalf("commits = %v", commits)
	}
}

func TestPullRequestCreatesForkBranchAndPR(t *testing.T) {
	fake := &fakeGitHub{}
	srv := httptest.NewServer(fake.handler(t))
	defer srv.Close()
	t.Setenv("GITHUB_API_URL", srv.URL)
	api, id := setupPRJob(t)

	rec, out := call(t, api, "POST", id, `{"token": "`+testToken+`"}`)
	if rec.Code != 201 {
		t.Fatalf("create: %d %s", rec.Code, rec.Body.String())
	}
	if out["url"] != "https://github.com/up/proj/pull/7" || out["forked"] != true || out["head"] != "alice:depexit/migrate-"+id {
		t.Fatalf("unexpected result %v", out)
	}
	// commits are chained on the analysed commit, one per changed file
	if len(fake.parents) != 2 || fake.parents[0] != "abc123def4567890" || fake.parents[1] != "c1" {
		t.Fatalf("commit parents = %v", fake.parents)
	}
	if fake.prBody["base"] != "main" || fake.prBody["head"] != "alice:depexit/migrate-"+id {
		t.Fatalf("PR request = %v", fake.prBody)
	}
	if strings.Contains(rec.Body.String(), testToken) {
		t.Fatal("token leaked into the response")
	}
	saved, _ := os.ReadFile(filepath.Join(api.store.jobDir(id), "pull_request.json"))
	if strings.Contains(string(saved), testToken) {
		t.Fatal("token persisted to disk")
	}

	// a second request returns the same PR instead of opening a duplicate
	before := len(fake.calls)
	rec2, out2 := call(t, api, "POST", id, `{"token": "`+testToken+`"}`)
	if rec2.Code != 200 || out2["number"].(float64) != 7 || len(fake.calls) != before {
		t.Fatalf("duplicate PR guard failed: %d %v (calls %d -> %d)", rec2.Code, out2, before, len(fake.calls))
	}
	if rec3, _ := call(t, api, "GET", id, ""); rec3.Code != 200 {
		t.Fatalf("GET saved PR: %d", rec3.Code)
	}
}

func TestPullRequestRejectsBadTokenAndMissingToken(t *testing.T) {
	fake := &fakeGitHub{}
	srv := httptest.NewServer(fake.handler(t))
	defer srv.Close()
	t.Setenv("GITHUB_API_URL", srv.URL)
	t.Setenv("GITHUB_TOKEN", "")
	api, id := setupPRJob(t)
	if rec, _ := call(t, api, "POST", id, `{}`); rec.Code != 400 {
		t.Fatalf("missing token should be 400, got %d", rec.Code)
	}
	rec, out := call(t, api, "POST", id, `{"token": "wrong"}`)
	if rec.Code != 502 && rec.Code != 400 {
		t.Fatalf("bad token: %d", rec.Code)
	}
	if !strings.Contains(out["error"].(map[string]any)["message"].(string), "rejected") {
		t.Fatalf("bad token message: %v", out)
	}
}
