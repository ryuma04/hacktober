package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

type Pipeline struct {
	cfg   Config
	store *Store
	ai    *AIClient
	sb    *Sandbox
}

func (p *Pipeline) setStage(id, stage, status, errMsg string) {
	now := time.Now().UTC()
	p.store.Update(id, func(j *Job) {
		for _, s := range j.Stages {
			if s.ID != stage {
				continue
			}
			s.Status = status
			switch status {
			case "running":
				s.StartedAt = &now
			case "completed", "failed", "skipped":
				s.FinishedAt = &now
				if s.StartedAt != nil {
					s.DurationS = float64(now.Sub(*s.StartedAt).Milliseconds()) / 1000
				}
				s.Error = errMsg
			}
		}
	})
}

func (p *Pipeline) stageDuration(id, stage string) float64 {
	j, _ := p.store.Snapshot(id)
	for _, s := range j.Stages {
		if s.ID == stage {
			return s.DurationS
		}
	}
	return 0
}

func (p *Pipeline) logf(id, stage, level, format string, args ...any) {
	p.store.Emit(id, "log", map[string]any{"stage": stage, "level": level, "message": fmt.Sprintf(format, args...)})
}

// stage runs fn as a named stage with start/complete/fail events. Returns fn's error.
func (p *Pipeline) stage(id, name string, errs map[string]string, mu *sync.Mutex, fn func() (map[string]any, error)) error {
	p.setStage(id, name, "running", "")
	p.store.Emit(id, "stage_started", map[string]any{"stage": name})
	stats, err := fn()
	if err != nil {
		p.setStage(id, name, "failed", err.Error())
		p.store.Emit(id, "stage_failed", map[string]any{"stage": name, "error": err.Error()})
		mu.Lock()
		errs[name] = err.Error()
		mu.Unlock()
		log.Printf("[%s] %s failed: %v", id, name, err)
		return err
	}
	p.setStage(id, name, "completed", "")
	p.store.Emit(id, "stage_completed", map[string]any{"stage": name, "duration_s": p.stageDuration(id, name), "stats": stats})
	return nil
}

func (p *Pipeline) skip(id, name, reason string) {
	p.setStage(id, name, "skipped", reason)
	p.store.Emit(id, "stage_skipped", map[string]any{"stage": name, "reason": reason})
}

// forwardAICalls turns the AI service's call records into SSE events.
func (p *Pipeline) forwardAICalls(id, stage string, out map[string]any) {
	calls, _ := out["ai_calls"].([]any)
	for _, c := range calls {
		m, ok := c.(map[string]any)
		if !ok {
			continue
		}
		m["stage"] = stage
		p.store.Emit(id, "ai_call", m)
		if ok, _ := m["ok"].(bool); !ok {
			errText := fmt.Sprint(m["error"])
			level := "warn"
			if strings.Contains(errText, "EXHAUSTED") {
				level = "error" // surfaced prominently: the operator must add API keys
			}
			p.logf(id, stage, level, "Gemma call '%v' failed: %v", m["purpose"], errText)
		}
	}
}

func (p *Pipeline) aiStage(ctx context.Context, id, stage, path string, body map[string]any, timeout time.Duration,
	errs map[string]string, mu *sync.Mutex, stats func(map[string]any) map[string]any) (map[string]any, error) {
	var out map[string]any
	err := p.stage(id, stage, errs, mu, func() (map[string]any, error) {
		var err error
		out, err = p.ai.Call(ctx, path, body, timeout)
		if err != nil {
			return nil, err
		}
		p.forwardAICalls(id, stage, out)
		if stats != nil {
			return stats(out), nil
		}
		return nil, nil
	})
	return out, err
}

func (p *Pipeline) Run(id string) {
	ctx := context.Background()
	job, _ := p.store.Snapshot(id)
	jobDir := p.store.jobDir(id)
	repo := filepath.Join(jobDir, "repo")
	errs := map[string]string{}
	var mu sync.Mutex
	p.store.Update(id, func(j *Job) { j.Status = "running" })
	p.store.Emit(id, "job_started", map[string]any{"repo_url": job.RepoURL})

	// 1. clone
	err := p.stage(id, "clone", errs, &mu, func() (map[string]any, error) {
		args := []string{"clone", "--depth", "1"}
		if job.Ref != "" && job.Ref != "HEAD" {
			args = append(args, "--branch", job.Ref)
		}
		args = append(args, job.RepoURL, repo)
		p.logf(id, "clone", "info", "git %s", strings.Join(args[:len(args)-1], " "))
		cctx, cancel := context.WithTimeout(ctx, 2*time.Minute)
		defer cancel()
		if out, err := runCmd(cctx, jobDir, "git", args...); err != nil {
			if job.Ref == "main" { // default branch may be named differently: retry without --branch
				_ = os.RemoveAll(repo)
				if out2, err2 := runCmd(cctx, jobDir, "git", "clone", "--depth", "1", job.RepoURL, repo); err2 != nil {
					return nil, fmt.Errorf("git clone failed: %s", lastLine(out2))
				}
			} else {
				return nil, fmt.Errorf("git clone failed: %s", lastLine(out))
			}
		}
		commit, _ := runCmd(cctx, repo, "git", "rev-parse", "HEAD")
		p.store.Update(id, func(j *Job) { j.Commit = commit })
		return map[string]any{"commit": commit}, nil
	})
	if err != nil {
		for _, s := range stageOrder[1:] {
			p.skip(id, s.ID, "clone failed")
		}
		p.finish(id, "failed", err.Error())
		return
	}
	job, _ = p.store.Snapshot(id)

	// 6. baseline sandbox in parallel with the analysis stages
	dockerOK := dockerAvailable(ctx)
	var baseWG sync.WaitGroup
	baselineOK := false
	if dockerOK {
		baseWG.Add(1)
		go func() {
			defer baseWG.Done()
			runDir := filepath.Join(jobDir, "runs", "baseline")
			e := p.stage(id, "sandbox_baseline", errs, &mu, func() (map[string]any, error) {
				work := filepath.Join(runDir, "repo")
				if err := copyTree(repo, work); err != nil {
					return nil, err
				}
				p.logf(id, "sandbox_baseline", "info", "Installing original dependencies in %s", p.sb.Image)
				r := p.sb.Run(ctx, id, "baseline", "baseline", work, runDir)
				p.logf(id, "sandbox_baseline", "info", "baseline: %s (install exit %s, pytest exit %s)", r.Status, codeStr(r.InstallExitCode), codeStr(r.TestExitCode))
				if r.Status == "error" || r.Status == "timeout" {
					return nil, fmt.Errorf("baseline run %s: %s", r.Status, r.Error)
				}
				return map[string]any{"status": r.Status, "duration_s": r.DurationS}, nil
			})
			baselineOK = e == nil
		}()
	} else {
		p.skip(id, "sandbox_baseline", "Docker is not available")
		mu.Lock()
		errs["sandbox_baseline"] = "Docker is not available on the host"
		mu.Unlock()
	}

	py := p.cfg.PythonVersion
	base := map[string]any{"job_dir": jobDir, "repo_dir": repo, "python_version": py}

	// 2-5. analysis (each later stage needs the previous one's output file)
	_, scanErr := p.aiStage(ctx, id, "scan", "/v1/scan", base, 8*time.Minute, errs, &mu, func(o map[string]any) map[string]any {
		deps, _ := o["dependencies"].([]any)
		atRisk := 0
		for _, d := range deps {
			if r, ok := d.(map[string]any)["risk"].(map[string]any); ok {
				if lv := r["level"]; lv == "medium" || lv == "high" || lv == "critical" {
					atRisk++
				}
				for _, ind := range r["indicators"].([]any) {
					im := ind.(map[string]any)
					if im["code"] == "KNOWN_VULNERABILITY" || im["code"] == "MANIFEST_DRIFT" || im["code"] == "UNDECLARED" {
						p.logf(id, "scan", "warn", "%v: %v", d.(map[string]any)["name"], im["detail"])
					}
				}
			}
		}
		return map[string]any{"dependencies": len(deps), "at_risk": atRisk}
	})
	migratedRepo := filepath.Join(jobDir, "runs", "migrated", "repo")
	var matErr error = fmt.Errorf("scan failed")
	if scanErr != nil {
		for _, s := range []string{"usage", "propose", "materialize"} {
			p.skip(id, s, "scan failed")
		}
	} else {
		matErr = p.analysisStages(ctx, id, base, migratedRepo, errs, &mu)
	}
	p.afterAnalysis(ctx, id, jobDir, job, base, migratedRepo, matErr, dockerOK, &baseWG, &baselineOK, errs, &mu)
}

func (p *Pipeline) analysisStages(ctx context.Context, id string, base map[string]any, migratedRepo string,
	errs map[string]string, mu *sync.Mutex) error {
	_, usageErr := p.aiStage(ctx, id, "usage", "/v1/usage", base, 8*time.Minute, errs, mu, func(o map[string]any) map[string]any {
		extra, _ := o["extra_indicators"].(map[string]any)
		for dep, inds := range extra {
			for _, ind := range inds.([]any) {
				im := ind.(map[string]any)
				p.logf(id, "usage", "warn", "%s: %v", dep, im["detail"])
			}
		}
		blast, _ := o["blast_radius"].(map[string]any)
		for dep, s := range blast {
			st, _ := s.(map[string]any)
			p.logf(id, "usage", "info", "blast radius %s: %v line(s) in %v file(s), +%v importing module(s), %v/%v test files reach it",
				dep, st["lines"], st["direct_files"], st["indirect_files"], st["test_files"], st["total_test_files"])
		}
		return map[string]any{"dependencies": o["dependencies"]}
	})
	if usageErr != nil {
		p.skip(id, "propose", "usage failed")
		p.skip(id, "materialize", "usage failed")
		return usageErr
	}
	_, propErr := p.aiStage(ctx, id, "propose", "/v1/propose", merge(base, map[string]any{"min_level": "medium"}), 15*time.Minute,
		errs, mu, func(o map[string]any) map[string]any {
			props, _ := o["proposals"].(map[string]any)
			n := 0
			for name, v := range props {
				pm := v.(map[string]any)
				if pm["strategy"] != "keep" {
					n++
					p.logf(id, "propose", "info", "%s → %v %v %v", name, pm["strategy"], nz(pm["package"]), nz(pm["version_spec"]))
				}
			}
			return map[string]any{"proposals": n}
		})
	if propErr != nil {
		p.skip(id, "materialize", "propose failed")
		return propErr
	}
	_, matErr := p.aiStage(ctx, id, "materialize", "/v1/materialize", merge(base, map[string]any{"out_repo_dir": migratedRepo}),
		15*time.Minute, errs, mu, func(o map[string]any) map[string]any {
			files, _ := o["files"].([]any)
			applied, rejected := 0, 0
			for _, f := range files {
				fm := f.(map[string]any)
				switch fm["status"] {
				case "applied":
					applied++
				case "rejected":
					rejected++
					p.logf(id, "materialize", "warn", "Rejected rewrite of %v: %v; original kept", fm["path"], fm["reason"])
				}
			}
			return map[string]any{"files_applied": applied, "files_rejected": rejected, "patch": o["patch"]}
		})
	return matErr
}

func (p *Pipeline) afterAnalysis(ctx context.Context, id, jobDir string, job *Job, base map[string]any, migratedRepo string,
	matErr error, dockerOK bool, baseWG *sync.WaitGroup, baselineOKp *bool, errs map[string]string, mu *sync.Mutex) {
	// 7. migrated sandbox
	baseWG.Wait()
	baselineOK := *baselineOKp
	runIDs := []string{}
	if baselineOK || fileExists(filepath.Join(jobDir, "runs", "baseline", "result.json")) {
		runIDs = append(runIDs, "baseline")
	}
	switch {
	case !dockerOK:
		p.skip(id, "sandbox_migrated", "Docker is not available")
	case matErr != nil || !fileExists(migratedRepo):
		p.skip(id, "sandbox_migrated", "migrated workspace was not built")
	default:
		_ = p.stage(id, "sandbox_migrated", errs, mu, func() (map[string]any, error) {
			runDir := filepath.Join(jobDir, "runs", "migrated")
			p.logf(id, "sandbox_migrated", "info", "Installing migrated dependencies in %s", p.sb.Image)
			r := p.sb.Run(ctx, id, "migrated", "migrated", migratedRepo, runDir)
			p.logf(id, "sandbox_migrated", "info", "migrated: %s (install exit %s, pytest exit %s)", r.Status, codeStr(r.InstallExitCode), codeStr(r.TestExitCode))
			if r.Status == "error" || r.Status == "timeout" {
				return nil, fmt.Errorf("migrated run %s: %s", r.Status, r.Error)
			}
			return map[string]any{"status": r.Status, "duration_s": r.DurationS}, nil
		})
		if fileExists(filepath.Join(jobDir, "runs", "migrated", "result.json")) {
			runIDs = append(runIDs, "migrated")
		}
	}

	// 8. compare
	if len(runIDs) > 0 {
		_, _ = p.aiStage(ctx, id, "compare", "/v1/compare", merge(base, map[string]any{"run_ids": runIDs}), 5*time.Minute,
			errs, mu, func(o map[string]any) map[string]any {
				fixed, regressed, still := 0, 0, 0
				gaps, _ := o["gaps"].([]any)
				for _, g := range gaps {
					switch g.(map[string]any)["change"] {
					case "fixed", "install_fixed":
						fixed++
					case "regressed", "install_regressed":
						regressed++
					case "still_failing":
						still++
					}
				}
				return map[string]any{"fixed": fixed, "regressed": regressed, "still_failing": still}
			})
	} else {
		p.skip(id, "compare", "no sandbox runs to compare")
	}

	// 9. capsule
	mu.Lock()
	stageErrs := map[string]string{}
	for k, v := range errs {
		stageErrs[k] = v
	}
	mu.Unlock()
	target := map[string]any{"repo_url": job.RepoURL, "ref": job.Ref, "commit": job.Commit}
	capOut, capErr := p.aiStage(ctx, id, "capsule", "/v1/capsule",
		merge(base, map[string]any{"target": target, "stage_errors": stageErrs, "base_url": "/api/analyses/" + id}),
		2*time.Minute, errs, mu, func(o map[string]any) map[string]any {
			return map[string]any{"schema_valid": o["schema_valid"]}
		})
	if capErr == nil {
		if sum, ok := capOut["summary"]; ok {
			b, _ := json.Marshal(sum)
			p.store.Update(id, func(j *Job) { j.Summary = b })
		}
	}
	status := "completed"
	mu.Lock()
	if len(errs) > 0 {
		status = "completed_with_errors"
	}
	mu.Unlock()
	if capErr != nil {
		status = "failed"
	}
	p.finish(id, status, "")
}

func (p *Pipeline) finish(id, status, errMsg string) {
	now := time.Now().UTC()
	p.store.Update(id, func(j *Job) {
		j.Status, j.FinishedAt = status, &now
		if errMsg != "" {
			j.Error = errMsg
		}
	})
	j, _ := p.store.Snapshot(id)
	data := map[string]any{"status": status}
	if len(j.Summary) > 0 {
		var s any
		_ = json.Unmarshal(j.Summary, &s)
		data["summary"] = s
	}
	if status == "failed" {
		data["error"] = j.Error
		p.store.Emit(id, "job_failed", data)
		return
	}
	p.store.Emit(id, "job_completed", data)
}

func merge(a, b map[string]any) map[string]any {
	out := map[string]any{}
	for k, v := range a {
		out[k] = v
	}
	for k, v := range b {
		out[k] = v
	}
	return out
}

func nz(v any) any {
	if v == nil {
		return ""
	}
	return v
}

func codeStr(c *int) string {
	if c == nil {
		return "-"
	}
	return fmt.Sprint(*c)
}

func lastLine(s string) string {
	lines := strings.Split(strings.TrimSpace(s), "\n")
	return lines[len(lines)-1]
}

func fileExists(p string) bool {
	_, err := os.Stat(p)
	return err == nil
}
