package main

// Pull request export: deliver the migration that passed in the Docker sandbox as a GitHub pull request.
//
// The branch starts at the exact commit DepExit analysed, and every file comes from the migrated workspace that ran
// in Docker (data/<id>/runs/migrated/repo) — nothing is regenerated. The capsule becomes the PR description.
// The GitHub token is used for this request only: it is never stored, logged or returned.

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"time"
)

type prRequest struct {
	Token  string `json:"token"`
	DryRun bool   `json:"dry_run"`
	Draft  bool   `json:"draft"`
}

type prCommit struct {
	Message string   `json:"message"`
	Files   []string `json:"files"`
}

type prPlan struct {
	Owner        string     `json:"owner"`
	Repo         string     `json:"repo"`
	BaseCommit   string     `json:"base_commit"`
	Branch       string     `json:"branch"`
	Title        string     `json:"title"`
	Body         string     `json:"body"`
	Commits      []prCommit `json:"commits"`
	FilesChanged []string   `json:"files_changed"`
}

type prResult struct {
	URL       string    `json:"url"`
	Number    int       `json:"number"`
	Branch    string    `json:"branch"`
	Head      string    `json:"head"` // owner:branch (owner is the fork when the token cannot push upstream)
	Forked    bool      `json:"forked"`
	Commits   int       `json:"commits"`
	CreatedAt time.Time `json:"created_at"`
}

var githubRepoRe = regexp.MustCompile(`^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$`)

func githubAPIBase() string {
	if v := strings.TrimRight(os.Getenv("GITHUB_API_URL"), "/"); v != "" {
		return v // tests point this at a fake server
	}
	return "https://api.github.com"
}

// buildPRPlan derives everything the PR needs from the finished analysis on disk.
func (a *API) buildPRPlan(id string, job *Job) (*prPlan, error) {
	m := githubRepoRe.FindStringSubmatch(job.RepoURL)
	if m == nil {
		return nil, fmt.Errorf("pull requests are supported for github.com repositories only")
	}
	if job.Commit == "" {
		return nil, fmt.Errorf("the analysed commit is unknown")
	}
	dir := a.store.jobDir(id)
	origRoot, migRoot := filepath.Join(dir, "repo"), filepath.Join(dir, "runs", "migrated", "repo")
	if !fileExists(migRoot) {
		return nil, fmt.Errorf("no migrated workspace: the migration was not built for this analysis")
	}
	var capsule struct {
		Summary struct {
			Verdict  string                      `json:"verdict"`
			Headline string                      `json:"headline"`
			AtRisk   int                         `json:"at_risk"`
			Total    int                         `json:"dependencies_total"`
			Baseline struct{ Passed, Total int } `json:"baseline"`
			Migrated struct {
				Passed, Total int
				Status        string `json:"status"`
			} `json:"migrated"`
			Gaps map[string]int `json:"gaps"`
		} `json:"summary"`
		AI struct {
			Model          string         `json:"model"`
			Provider       string         `json:"provider"`
			ModelsUsed     map[string]int `json:"models_used"`
			FallbackModels []string       `json:"fallback_models_used"`
		} `json:"ai"`
		Dependencies []struct {
			Name          string `json:"name"`
			PinnedVersion string `json:"pinned_version"`
			LatestVersion string `json:"latest_version"`
			Risk          struct {
				Level      string `json:"level"`
				Score      int    `json:"score"`
				Indicators []struct {
					Code string `json:"code"`
				} `json:"indicators"`
			} `json:"risk"`
			Replacement *struct {
				Strategy    string `json:"strategy"`
				Package     string `json:"package"`
				VersionSpec string `json:"version_spec"`
				Model       string `json:"model"`
			} `json:"replacement"`
			Migration *struct {
				Applied          bool     `json:"applied"`
				NotAppliedReason string   `json:"not_applied_reason"`
				FilesChanged     []string `json:"files_changed"`
			} `json:"migration"`
			CompatibilityGaps []struct {
				TestID      string `json:"test_id"`
				Change      string `json:"change"`
				Explanation string `json:"explanation"`
			} `json:"compatibility_gaps"`
		} `json:"dependencies"`
		Limitations []string `json:"limitations"`
	}
	raw, err := os.ReadFile(filepath.Join(dir, "capsule.json"))
	if err != nil {
		return nil, fmt.Errorf("capsule not available yet")
	}
	if err := json.Unmarshal(raw, &capsule); err != nil {
		return nil, fmt.Errorf("capsule is not valid JSON: %w", err)
	}

	// changed files = the exact difference between the clone and the tested workspace
	orig, mig := listTree(origRoot), listTree(migRoot)
	var changed []string
	for p := range mig {
		if _, ok := orig[p]; !ok || !sameFile(filepath.Join(origRoot, filepath.FromSlash(p)), filepath.Join(migRoot, filepath.FromSlash(p))) {
			changed = append(changed, p)
		}
	}
	for p := range orig {
		if _, ok := mig[p]; !ok {
			changed = append(changed, p) // removed in the migration
		}
	}
	sort.Strings(changed)
	if len(changed) == 0 {
		return nil, fmt.Errorf("the migration changed no files, so there is nothing to propose")
	}

	// one commit per changed file, named after the dependencies whose migration touched it
	depsFor := map[string][]string{}
	for _, d := range capsule.Dependencies {
		if d.Migration == nil || !d.Migration.Applied {
			continue
		}
		for _, f := range d.Migration.FilesChanged {
			depsFor[f] = append(depsFor[f], d.Name)
		}
	}
	var commits []prCommit
	for _, f := range changed {
		deps := depsFor[f]
		sort.Strings(deps)
		verb := "Update"
		if _, ok := mig[f]; !ok {
			verb = "Remove"
		} else if _, ok := orig[f]; !ok {
			verb = "Add"
		}
		msg := fmt.Sprintf("%s %s", verb, f)
		if len(deps) > 0 {
			msg = fmt.Sprintf("%s for %s migration", msg, strings.Join(deps, ", "))
		}
		commits = append(commits, prCommit{Message: msg + "\n\nGenerated by DepExit from the migrated workspace that passed the sandbox tests.", Files: []string{f}})
	}

	s := capsule.Summary
	var b strings.Builder
	fmt.Fprintf(&b, "## Dependency Exit Capsule — automated migration\n\n")
	fmt.Fprintf(&b, "**Verdict:** `%s` — %s\n\n", s.Verdict, s.Headline)
	fmt.Fprintf(&b, "| | Baseline (original deps) | This PR (migrated) |\n|---|---|---|\n")
	fmt.Fprintf(&b, "| Tests passing in Docker (`python:3.12-slim`, offline) | %d / %d | %d / %d |\n\n",
		s.Baseline.Passed, s.Baseline.Total, s.Migrated.Passed, s.Migrated.Total)
	fmt.Fprintf(&b, "Analysed commit `%s` of %s · %d of %d dependencies at risk · gaps: %d fixed, %d regressed, %d still failing.\n\n",
		short(job.Commit), job.RepoURL, s.AtRisk, s.Total, s.Gaps["fixed"], s.Gaps["regressed"], s.Gaps["still_failing"])
	fmt.Fprintf(&b, "### Changes\n\n| Dependency | Risk | Change | Model | Applied |\n|---|---|---|---|---|\n")
	for _, d := range capsule.Dependencies {
		if d.Replacement == nil || d.Replacement.Strategy == "keep" {
			continue
		}
		change := strings.TrimSpace(d.Replacement.Strategy + " " + d.Replacement.Package + " " + d.Replacement.VersionSpec)
		applied := "—"
		if d.Migration != nil {
			applied = "✅"
			if !d.Migration.Applied {
				applied = "❌ not included"
			}
		}
		codes := make([]string, 0, len(d.Risk.Indicators))
		for _, ind := range d.Risk.Indicators {
			codes = append(codes, ind.Code)
		}
		fmt.Fprintf(&b, "| `%s` %s | %s (%d): %s | %s | %s | %s |\n", d.Name, pinStr(d.PinnedVersion, d.LatestVersion),
			d.Risk.Level, d.Risk.Score, strings.Join(codes, ", "), mdEscape(change), nz2(d.Replacement.Model, "computed"), applied)
	}
	gapCount := 0
	for _, d := range capsule.Dependencies {
		for _, g := range d.CompatibilityGaps {
			if gapCount == 0 {
				fmt.Fprintf(&b, "\n### Compatibility gaps (measured)\n\n")
			}
			gapCount++
			fmt.Fprintf(&b, "- `%s` **%s** (%s): %s\n", nz2(g.TestID, "install"), g.Change, d.Name, mdEscape(trimTo(g.Explanation, 300)))
		}
	}
	if len(capsule.Limitations) > 0 {
		fmt.Fprintf(&b, "\n### Limitations\n\n")
		for _, l := range capsule.Limitations {
			fmt.Fprintf(&b, "- %s\n", mdEscape(trimTo(l, 400)))
		}
	}
	models := make([]string, 0, len(capsule.AI.ModelsUsed))
	for m, n := range capsule.AI.ModelsUsed {
		models = append(models, fmt.Sprintf("%s ×%d", m, n))
	}
	sort.Strings(models)
	fmt.Fprintf(&b, "\n### How this PR was made\n\nDepExit cloned the repository at `%s`, scanned dependencies (PyPI, OSV, AST), "+
		"asked Gemma 4 via %s for replacements and code edits (%s), applied them to a copy, and ran the test suite in Docker "+
		"before and after. Every file in this PR is byte-for-byte the code that passed those tests. Please review — the "+
		"replacement choices are AI-generated.\n", short(job.Commit), nz2(capsule.AI.Provider, "Google AI Studio"), strings.Join(models, ", "))
	body := b.String()
	if len(body) > 60000 {
		body = body[:60000] + "\n\n… (truncated; see the full capsule)\n"
	}

	title := "DepExit: migrate at-risk dependencies"
	var names []string
	for _, d := range capsule.Dependencies {
		if d.Migration != nil && d.Migration.Applied && d.Replacement != nil && d.Replacement.Strategy != "keep" {
			names = append(names, d.Name)
		}
	}
	if len(names) > 0 && len(names) <= 4 {
		title = "DepExit: migrate " + strings.Join(names, ", ")
	} else if len(names) > 4 {
		title = fmt.Sprintf("DepExit: migrate %s and %d more dependencies", strings.Join(names[:3], ", "), len(names)-3)
	}
	return &prPlan{
		Owner: m[1], Repo: m[2], BaseCommit: job.Commit,
		Branch: "depexit/migrate-" + id, Title: title, Body: body, Commits: commits, FilesChanged: changed,
	}, nil
}

func short(sha string) string {
	if len(sha) > 10 {
		return sha[:10]
	}
	return sha
}

func pinStr(pinned, latest string) string {
	if pinned == "" {
		return ""
	}
	return fmt.Sprintf("%s → %s", pinned, latest)
}

func nz2(s, def string) string {
	if strings.TrimSpace(s) == "" {
		return def
	}
	return s
}

func trimTo(s string, n int) string {
	if len(s) > n {
		return s[:n] + "…"
	}
	return s
}

func mdEscape(s string) string {
	return strings.ReplaceAll(strings.ReplaceAll(s, "|", "\\|"), "\n", " ")
}

// ---------- GitHub REST client (minimal) ----------

type ghClient struct {
	base  string
	token string
	http  *http.Client
}

type ghError struct {
	Status  int
	Message string
}

func (e *ghError) Error() string { return fmt.Sprintf("GitHub API %d: %s", e.Status, e.Message) }

func (c *ghClient) do(ctx context.Context, method, path string, body, out any) error {
	var rd io.Reader
	if body != nil {
		b, _ := json.Marshal(body)
		rd = bytes.NewReader(b)
	}
	req, _ := http.NewRequestWithContext(ctx, method, c.base+path, rd)
	req.Header.Set("Authorization", "Bearer "+c.token)
	req.Header.Set("Accept", "application/vnd.github+json")
	req.Header.Set("X-GitHub-Api-Version", "2022-11-28")
	req.Header.Set("User-Agent", "DepExit")
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return fmt.Errorf("GitHub API %s %s: %w", method, path, err)
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)
	if resp.StatusCode >= 300 {
		var e struct {
			Message string `json:"message"`
			Errors  []struct {
				Message string `json:"message"`
			} `json:"errors"`
		}
		_ = json.Unmarshal(raw, &e)
		msg := e.Message
		for _, x := range e.Errors {
			if x.Message != "" {
				msg += ": " + x.Message
			}
		}
		return &ghError{Status: resp.StatusCode, Message: nz2(msg, http.StatusText(resp.StatusCode))}
	}
	if out != nil && len(raw) > 0 {
		return json.Unmarshal(raw, out)
	}
	return nil
}

// createPR performs the GitHub calls: (fork if needed) → blobs/trees/commits on top of the analysed commit →
// branch → pull request.
func (a *API) createPR(ctx context.Context, id string, plan *prPlan, token string, draft bool) (*prResult, error) {
	gh := &ghClient{base: githubAPIBase(), token: token, http: &http.Client{Timeout: 30 * time.Second}}
	var user struct {
		Login string `json:"login"`
	}
	if err := gh.do(ctx, "GET", "/user", nil, &user); err != nil {
		return nil, fmt.Errorf("the token was rejected by GitHub (%v)", err)
	}
	var repo struct {
		DefaultBranch string `json:"default_branch"`
		Permissions   struct {
			Push bool `json:"push"`
		} `json:"permissions"`
	}
	if err := gh.do(ctx, "GET", fmt.Sprintf("/repos/%s/%s", plan.Owner, plan.Repo), nil, &repo); err != nil {
		return nil, err
	}
	target, forked := plan.Owner+"/"+plan.Repo, false
	headOwner := plan.Owner
	if !repo.Permissions.Push {
		var fork struct {
			FullName string `json:"full_name"`
			Owner    struct {
				Login string `json:"login"`
			} `json:"owner"`
		}
		if err := gh.do(ctx, "POST", fmt.Sprintf("/repos/%s/%s/forks", plan.Owner, plan.Repo), map[string]any{"default_branch_only": true}, &fork); err != nil {
			return nil, fmt.Errorf("cannot push to %s/%s and forking failed: %w", plan.Owner, plan.Repo, err)
		}
		target, forked, headOwner = fork.FullName, true, fork.Owner.Login
		// forks are created asynchronously: wait until the analysed commit is readable in the fork
		ready := false
		for i := 0; i < 20 && !ready; i++ {
			if err := gh.do(ctx, "GET", fmt.Sprintf("/repos/%s/git/commits/%s", target, plan.BaseCommit), nil, nil); err == nil {
				ready = true
				break
			}
			select {
			case <-ctx.Done():
				return nil, ctx.Err()
			case <-time.After(2 * time.Second):
			}
		}
		if !ready {
			return nil, fmt.Errorf("the fork %s is not ready yet; try again in a minute", target)
		}
	}

	var base struct {
		Tree struct {
			SHA string `json:"sha"`
		} `json:"tree"`
	}
	if err := gh.do(ctx, "GET", fmt.Sprintf("/repos/%s/git/commits/%s", target, plan.BaseCommit), nil, &base); err != nil {
		return nil, fmt.Errorf("the analysed commit %s is not in %s: %w", short(plan.BaseCommit), target, err)
	}
	migRoot := filepath.Join(a.store.jobDir(id), "runs", "migrated", "repo")
	parent, tree := plan.BaseCommit, base.Tree.SHA
	for _, c := range plan.Commits {
		var entries []map[string]any
		for _, f := range c.Files {
			full := filepath.Join(migRoot, filepath.FromSlash(f))
			data, err := os.ReadFile(full)
			if err != nil { // removed by the migration
				entries = append(entries, map[string]any{"path": f, "mode": "100644", "type": "blob", "sha": nil})
				continue
			}
			var blob struct {
				SHA string `json:"sha"`
			}
			if err := gh.do(ctx, "POST", fmt.Sprintf("/repos/%s/git/blobs", target),
				map[string]any{"content": base64.StdEncoding.EncodeToString(data), "encoding": "base64"}, &blob); err != nil {
				return nil, err
			}
			entries = append(entries, map[string]any{"path": f, "mode": "100644", "type": "blob", "sha": blob.SHA})
		}
		var newTree struct {
			SHA string `json:"sha"`
		}
		if err := gh.do(ctx, "POST", fmt.Sprintf("/repos/%s/git/trees", target), map[string]any{"base_tree": tree, "tree": entries}, &newTree); err != nil {
			return nil, err
		}
		var commit struct {
			SHA string `json:"sha"`
		}
		if err := gh.do(ctx, "POST", fmt.Sprintf("/repos/%s/git/commits", target),
			map[string]any{"message": c.Message, "tree": newTree.SHA, "parents": []string{parent}}, &commit); err != nil {
			return nil, err
		}
		parent, tree = commit.SHA, newTree.SHA
	}
	branch := plan.Branch
	if err := gh.do(ctx, "POST", fmt.Sprintf("/repos/%s/git/refs", target), map[string]any{"ref": "refs/heads/" + branch, "sha": parent}, nil); err != nil {
		var ge *ghError
		if asGH(err, &ge) && ge.Status == 422 { // branch exists from an earlier attempt: move it to the new commits
			if err := gh.do(ctx, "PATCH", fmt.Sprintf("/repos/%s/git/refs/heads/%s", target, branch), map[string]any{"sha": parent, "force": true}, nil); err != nil {
				return nil, err
			}
		} else {
			return nil, err
		}
	}
	var pr struct {
		HTMLURL string `json:"html_url"`
		Number  int    `json:"number"`
	}
	head := branch
	if forked {
		head = headOwner + ":" + branch
	}
	if err := gh.do(ctx, "POST", fmt.Sprintf("/repos/%s/%s/pulls", plan.Owner, plan.Repo), map[string]any{
		"title": plan.Title, "body": plan.Body, "head": head, "base": repo.DefaultBranch, "draft": draft,
		"maintainer_can_modify": true,
	}, &pr); err != nil {
		return nil, err
	}
	return &prResult{URL: pr.HTMLURL, Number: pr.Number, Branch: branch, Head: head, Forked: forked,
		Commits: len(plan.Commits), CreatedAt: time.Now().UTC()}, nil
}

func asGH(err error, target **ghError) bool {
	ge, ok := err.(*ghError)
	if ok {
		*target = ge
	}
	return ok
}

// pullRequest: POST /api/analyses/{id}/pull-request  {token?, dry_run?, draft?}
// GET returns the PR already opened for this analysis (if any).
func (a *API) pullRequest(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	job, ok := a.store.Snapshot(id)
	if !ok {
		writeErr(w, 404, "not_found", "analysis "+id+" not found")
		return
	}
	savedPath := filepath.Join(a.store.jobDir(id), "pull_request.json")
	if r.Method == http.MethodGet {
		b, err := os.ReadFile(savedPath)
		if err != nil {
			writeErr(w, 404, "not_found", "no pull request has been opened for this analysis")
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write(b)
		return
	}
	if !finished(job.Status) {
		writeErr(w, 409, "conflict", "analysis is still running")
		return
	}
	var req prRequest
	_ = json.NewDecoder(io.LimitReader(r.Body, 1<<16)).Decode(&req)
	plan, err := a.buildPRPlan(id, job)
	if err != nil {
		writeErr(w, 409, "conflict", err.Error())
		return
	}
	if req.DryRun {
		writeJSON(w, http.StatusOK, map[string]any{"dry_run": true, "plan": plan})
		return
	}
	if b, err := os.ReadFile(savedPath); err == nil { // never open duplicates
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(b)
		return
	}
	token := strings.TrimSpace(req.Token)
	if token == "" {
		token = strings.TrimSpace(os.Getenv("GITHUB_TOKEN"))
	}
	if token == "" {
		writeErr(w, 400, "bad_request", "a GitHub token is required (fine-grained token with Contents + Pull requests write access)")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 3*time.Minute)
	defer cancel()
	res, err := a.createPR(ctx, id, plan, token, req.Draft)
	if err != nil {
		code := 502
		var ge *ghError
		if asGH(err, &ge) && (ge.Status == 401 || ge.Status == 403 || ge.Status == 404) {
			code = 400
		}
		writeErr(w, code, "github_error", err.Error())
		return
	}
	b, _ := json.MarshalIndent(res, "", "  ")
	_ = os.WriteFile(savedPath, b, 0o644)
	a.store.Emit(id, "log", map[string]any{"stage": "capsule", "level": "info", "message": "Pull request opened: " + res.URL})
	writeJSON(w, http.StatusCreated, res)
}
