package main

import (
	"bytes"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// Workspace browsing for the code viewer: the original clone (data/<id>/repo) next to the migrated workspace that
// actually ran in Docker (data/<id>/runs/migrated/repo). Read-only by design — the files are evidence.

const maxViewBytes = 1 << 20 // files larger than 1 MiB are listed but not served

var skipDirs = map[string]bool{".git": true, "__pycache__": true, ".depexit": true, ".venv": true,
	"node_modules": true, ".pytest_cache": true, ".mypy_cache": true}

type WorkspaceFile struct {
	Path         string `json:"path"`
	Status       string `json:"status"` // unchanged | modified | added | removed
	SizeOriginal int64  `json:"size_original,omitempty"`
	SizeMigrated int64  `json:"size_migrated,omitempty"`
	Viewable     bool   `json:"viewable"`
}

func listTree(root string) map[string]int64 {
	out := map[string]int64{}
	_ = filepath.Walk(root, func(p string, info os.FileInfo, err error) error {
		if err != nil {
			return nil
		}
		if info.IsDir() {
			if skipDirs[info.Name()] && p != root {
				return filepath.SkipDir
			}
			return nil
		}
		if !info.Mode().IsRegular() || strings.HasSuffix(info.Name(), ".pyc") {
			return nil
		}
		rel, _ := filepath.Rel(root, p)
		out[filepath.ToSlash(rel)] = info.Size()
		return nil
	})
	return out
}

func sameFile(a, b string) bool {
	x, err1 := os.ReadFile(a)
	y, err2 := os.ReadFile(b)
	if err1 != nil || err2 != nil {
		return false
	}
	norm := func(s []byte) []byte { return bytes.ReplaceAll(s, []byte("\r\n"), []byte("\n")) }
	return bytes.Equal(norm(x), norm(y))
}

// files lists the union of both workspaces with a per-file change status.
func (a *API) files(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if _, ok := a.store.Snapshot(id); !ok {
		writeErr(w, 404, "not_found", "analysis "+id+" not found")
		return
	}
	origRoot := filepath.Join(a.store.jobDir(id), "repo")
	migRoot := filepath.Join(a.store.jobDir(id), "runs", "migrated", "repo")
	if !fileExists(origRoot) {
		writeErr(w, 409, "conflict", "the repository has not been cloned yet")
		return
	}
	orig := listTree(origRoot)
	migAvailable := fileExists(migRoot)
	mig := map[string]int64{}
	if migAvailable {
		mig = listTree(migRoot)
	}
	seen := map[string]bool{}
	var out []WorkspaceFile
	add := func(path string) {
		if seen[path] {
			return
		}
		seen[path] = true
		so, inOrig := orig[path]
		sm, inMig := mig[path]
		f := WorkspaceFile{Path: path, SizeOriginal: so, SizeMigrated: sm}
		switch {
		case !migAvailable:
			f.Status = "unchanged"
		case inOrig && !inMig:
			f.Status = "removed"
		case !inOrig && inMig:
			f.Status = "added"
		case sameFile(filepath.Join(origRoot, filepath.FromSlash(path)), filepath.Join(migRoot, filepath.FromSlash(path))):
			f.Status = "unchanged"
		default:
			f.Status = "modified"
		}
		f.Viewable = so <= maxViewBytes && sm <= maxViewBytes
		out = append(out, f)
	}
	for p := range orig {
		add(p)
	}
	for p := range mig {
		add(p)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Path < out[j].Path })
	changed := 0
	for _, f := range out {
		if f.Status != "unchanged" {
			changed++
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{"files": out, "changed": changed, "migrated_available": migAvailable})
}

// originalFile serves one file from the original clone (counterpart of migratedFile).
func (a *API) originalFile(w http.ResponseWriter, r *http.Request) {
	a.serveWorkspaceFile(w, r, filepath.Join("repo"))
}

func (a *API) serveWorkspaceFile(w http.ResponseWriter, r *http.Request, sub string) {
	id := r.PathValue("id")
	if _, ok := a.store.Snapshot(id); !ok {
		writeErr(w, 404, "not_found", "analysis "+id+" not found")
		return
	}
	root := filepath.Join(a.store.jobDir(id), sub)
	full := filepath.Join(root, filepath.FromSlash(r.PathValue("path")))
	if rel, err := filepath.Rel(root, full); err != nil || strings.HasPrefix(rel, "..") {
		writeErr(w, 400, "bad_request", "invalid path")
		return
	}
	info, err := os.Stat(full)
	if err != nil || info.IsDir() {
		writeErr(w, 404, "not_found", "file not found in this workspace")
		return
	}
	if info.Size() > maxViewBytes {
		writeErr(w, 413, "too_large", "file is larger than 1 MiB")
		return
	}
	b, err := os.ReadFile(full)
	if err != nil {
		writeErr(w, 404, "not_found", "file not readable")
		return
	}
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	_, _ = w.Write(b)
}
