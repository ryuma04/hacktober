package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

type API struct {
	cfg    Config
	store  *Store
	pipe   *Pipeline
	authDB *AuthDB
	runJob func(id string)
}

var repoURLRe = regexp.MustCompile(`^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?(\.git)?/?$`)
var runIDRe = regexp.MustCompile(`^[a-z0-9_-]+$`)

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(v)
}

func writeErr(w http.ResponseWriter, code int, kind, msg string) {
	writeJSON(w, code, map[string]any{"error": map[string]string{"code": kind, "message": msg}})
}

func (a *API) routes() http.Handler {
	mux := http.NewServeMux()
	// Auth routes (Neon PostgreSQL)
	mux.HandleFunc("POST /api/auth/register", a.register)
	mux.HandleFunc("POST /api/auth/login", a.login)
	mux.HandleFunc("GET /api/auth/me", a.me)

	mux.HandleFunc("GET /api/health", a.health)
	mux.HandleFunc("POST /api/analyses", a.create)
	mux.HandleFunc("GET /api/analyses", a.list)
	mux.HandleFunc("GET /api/analyses/{id}", a.get)
	mux.HandleFunc("GET /api/analyses/{id}/events", a.events)
	mux.HandleFunc("GET /api/analyses/{id}/capsule", a.artifact("capsule.json", "application/json"))
	mux.HandleFunc("GET /api/analyses/{id}/capsule.md", a.artifact("CAPSULE.md", "text/markdown; charset=utf-8"))
	mux.HandleFunc("GET /api/analyses/{id}/capsule.pdf", a.capsulePDF)
	mux.HandleFunc("GET /api/analyses/{id}/patch.diff", a.artifact("patch.diff", "text/x-diff; charset=utf-8"))
	mux.HandleFunc("GET /api/analyses/{id}/runs/{run}/log", a.runLog)
	mux.HandleFunc("GET /api/analyses/{id}/runs/{run}/junit", a.junit)
	mux.HandleFunc("GET /api/analyses/{id}/migrated/{path...}", a.migratedFile)
	mux.HandleFunc("GET /api/analyses/{id}/original/{path...}", a.originalFile)
	mux.HandleFunc("GET /api/analyses/{id}/files", a.files)
	mux.HandleFunc("POST /api/analyses/{id}/pull-request", a.pullRequest)
	mux.HandleFunc("GET /api/analyses/{id}/pull-request", a.pullRequest)
	return a.cors(mux)
}

func (a *API) cors(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		origin := r.Header.Get("Origin")
		allowed := strings.HasPrefix(origin, "http://localhost") || strings.HasPrefix(origin, "http://127.0.0.1") ||
			strings.HasPrefix(origin, "vscode-webview://")
		for _, o := range a.cfg.AllowedOrigins {
			if o == origin || o == "*" {
				allowed = true
			}
		}
		if origin != "" && allowed {
			w.Header().Set("Access-Control-Allow-Origin", origin)
			w.Header().Set("Vary", "Origin")
			w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
			w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
		}
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func (a *API) health(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	docker := dockerAvailable(ctx)
	out := map[string]any{"status": "ok", "docker": docker, "sandbox_image_ready": docker && imageReady(ctx, a.cfg.SandboxImage),
		"ai_service": false, "gemma": map[string]any{"configured": false, "model": "", "reachable": false}, "version": "0.1.0"}
	if h, ok := a.pipe.ai.Health(ctx); ok {
		out["ai_service"] = true
		if g, ok := h["gemma"].(map[string]any); ok {
			out["gemma"] = g
		}
	}
	writeJSON(w, http.StatusOK, out)
}

func (a *API) create(w http.ResponseWriter, r *http.Request) {
	var body struct {
		RepoURL string  `json:"repo_url"`
		Ref     string  `json:"ref"`
		Options Options `json:"options"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil && err.Error() != "EOF" {
		writeErr(w, 400, "bad_request", "invalid JSON body")
		return
	}
	if body.RepoURL == "" {
		body.RepoURL = a.cfg.DefaultRepoURL
	}
	body.RepoURL = strings.TrimSpace(body.RepoURL)
	if !repoURLRe.MatchString(body.RepoURL) {
		writeErr(w, 400, "bad_request", "repo_url must look like https://github.com/<owner>/<repo>")
		return
	}
	if body.Ref == "" {
		body.Ref = "main"
	}
	j := a.store.Create(strings.TrimSuffix(body.RepoURL, "/"), body.Ref, body.Options)
	if a.runJob != nil {
		go a.runJob(j.ID)
	} else if a.pipe != nil {
		go a.pipe.Run(j.ID)
	}
	writeJSON(w, http.StatusAccepted, map[string]any{"id": j.ID, "status": j.Status, "created_at": j.CreatedAt,
		"links": map[string]string{"self": "/api/analyses/" + j.ID, "events": "/api/analyses/" + j.ID + "/events"}})
}

func (a *API) list(w http.ResponseWriter, r *http.Request) {
	items := []map[string]any{}
	for _, j := range a.store.List() {
		it := map[string]any{"id": j.ID, "repo_url": j.RepoURL, "status": j.Status, "created_at": j.CreatedAt}
		if len(j.Summary) > 0 {
			var s map[string]any
			_ = json.Unmarshal(j.Summary, &s)
			it["summary"] = map[string]any{"dependencies_total": s["dependencies_total"], "at_risk": s["at_risk"]}
		}
		items = append(items, it)
	}
	writeJSON(w, http.StatusOK, map[string]any{"items": items})
}

func (a *API) get(w http.ResponseWriter, r *http.Request) {
	j, ok := a.store.Snapshot(r.PathValue("id"))
	if !ok {
		writeErr(w, 404, "not_found", "analysis "+r.PathValue("id")+" not found")
		return
	}
	writeJSON(w, http.StatusOK, j)
}

func finished(status string) bool {
	return status == "completed" || status == "completed_with_errors" || status == "failed"
}

func (a *API) events(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	past, ch, cancel, ok := a.store.Subscribe(id)
	if !ok {
		writeErr(w, 404, "not_found", "analysis "+id+" not found")
		return
	}
	defer cancel()
	flusher, _ := w.(http.Flusher)
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.WriteHeader(http.StatusOK)
	send := func(ev Event) bool {
		b, _ := json.Marshal(ev.Data)
		if _, err := fmt.Fprintf(w, "event: %s\ndata: %s\n\n", ev.Type, b); err != nil {
			return false
		}
		if flusher != nil {
			flusher.Flush()
		}
		return ev.Type != "job_completed" && ev.Type != "job_failed"
	}
	for _, ev := range past {
		if !send(ev) {
			return
		}
	}
	if j, _ := a.store.Snapshot(id); finished(j.Status) {
		return
	}
	ping := time.NewTicker(15 * time.Second)
	defer ping.Stop()
	for {
		select {
		case <-r.Context().Done():
			return
		case ev := <-ch:
			if !send(ev) {
				return
			}
		case <-ping.C:
			_, _ = fmt.Fprint(w, ": ping\n\n")
			if flusher != nil {
				flusher.Flush()
			}
		}
	}
}

// capsulePDF serves the PDF report, rendering it first (via the AI service) for analyses that predate it.
func (a *API) capsulePDF(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	j, ok := a.store.Snapshot(id)
	if !ok {
		writeErr(w, 404, "not_found", "analysis "+id+" not found")
		return
	}
	dir := a.store.jobDir(id)
	pdfPath := filepath.Join(dir, "capsule.pdf")
	if !fileExists(pdfPath) {
		if !finished(j.Status) {
			writeErr(w, 409, "conflict", "analysis is still running")
			return
		}
		if !fileExists(filepath.Join(dir, "capsule.json")) {
			writeErr(w, 404, "not_found", "no capsule was produced for this analysis")
			return
		}
		if _, err := a.pipe.ai.Call(r.Context(), "/v1/pdf", map[string]any{"job_dir": dir}, 60*time.Second); err != nil {
			writeErr(w, 502, "internal", "could not render the PDF: "+err.Error())
			return
		}
	}
	b, err := os.ReadFile(pdfPath)
	if err != nil {
		writeErr(w, 404, "not_found", "capsule.pdf was not produced for this analysis")
		return
	}
	w.Header().Set("Content-Type", "application/pdf")
	disp := "inline"
	if r.URL.Query().Get("download") == "1" {
		disp = "attachment"
	}
	w.Header().Set("Content-Disposition", fmt.Sprintf(`%s; filename="DepExit-%s.pdf"`, disp, id))
	_, _ = w.Write(b)
}

func (a *API) artifact(name, ctype string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("id")
		j, ok := a.store.Snapshot(id)
		if !ok {
			writeErr(w, 404, "not_found", "analysis "+id+" not found")
			return
		}
		path := filepath.Join(a.store.jobDir(id), name)
		if !finished(j.Status) && !fileExists(path) {
			writeErr(w, 409, "conflict", "analysis is still running")
			return
		}
		b, err := os.ReadFile(path)
		if err != nil {
			writeErr(w, 404, "not_found", name+" was not produced for this analysis")
			return
		}
		w.Header().Set("Content-Type", ctype)
		if r.URL.Query().Get("download") == "1" {
			w.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="%s-%s"`, id, name))
		}
		_, _ = w.Write(b)
	}
}

func (a *API) runFile(w http.ResponseWriter, r *http.Request, file, ctype string) {
	id, run := r.PathValue("id"), r.PathValue("run")
	if _, ok := a.store.Snapshot(id); !ok || !runIDRe.MatchString(run) {
		writeErr(w, 404, "not_found", "run not found")
		return
	}
	b, err := os.ReadFile(filepath.Join(a.store.jobDir(id), "runs", run, file))
	if err != nil {
		writeErr(w, 404, "not_found", file+" not found for run "+run)
		return
	}
	w.Header().Set("Content-Type", ctype)
	_, _ = w.Write(b)
}

func (a *API) runLog(w http.ResponseWriter, r *http.Request) {
	stream := r.URL.Query().Get("stream")
	if stream != "install" && stream != "test" {
		stream = "test"
	}
	a.runFile(w, r, stream+".log", "text/plain; charset=utf-8")
}

// migratedFile serves one file from the migrated workspace (used by the VS Code quick fix).
func (a *API) migratedFile(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if _, ok := a.store.Snapshot(id); !ok {
		writeErr(w, 404, "not_found", "analysis "+id+" not found")
		return
	}
	root := filepath.Join(a.store.jobDir(id), "runs", "migrated", "repo")
	full := filepath.Join(root, filepath.FromSlash(r.PathValue("path")))
	if rel, err := filepath.Rel(root, full); err != nil || strings.HasPrefix(rel, "..") {
		writeErr(w, 400, "bad_request", "invalid path")
		return
	}
	b, err := os.ReadFile(full)
	if err != nil {
		writeErr(w, 404, "not_found", "file not in migrated workspace")
		return
	}
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	_, _ = w.Write(b)
}

func (a *API) junit(w http.ResponseWriter, r *http.Request) {
	a.runFile(w, r, "junit.xml", "application/xml")
}
