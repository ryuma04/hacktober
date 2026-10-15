package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

// RunResult mirrors runs/<id>/result.json (read by the AI service's compare stage).
type RunResult struct {
	RunID           string   `json:"run_id"`
	Kind            string   `json:"kind"`
	Image           string   `json:"image"`
	Command         []string `json:"command"`
	InstallCommand  []string `json:"install_command"`
	InstallExitCode *int     `json:"install_exit_code,omitempty"`
	TestExitCode    *int     `json:"test_exit_code,omitempty"`
	Status          string   `json:"status"`
	DurationS       float64  `json:"duration_s"`
	StartedAt       string   `json:"started_at"`
	FinishedAt      string   `json:"finished_at"`
	Error           string   `json:"error,omitempty"`
}

type Sandbox struct {
	Image   string
	Timeout time.Duration
	// OnLine, if set, receives every output line of a sandbox container (live telemetry over SSE).
	OnLine func(jobID, runID, stream, line string)
}

// MaxLiveLines caps how many lines per stream are streamed live; the log file always has everything.
const MaxLiveLines = 400

// lineWriter tees container output to the log file and emits it line by line.
type lineWriter struct {
	file    io.Writer
	emit    func(string)
	buf     []byte
	emitted int
}

func (w *lineWriter) Write(p []byte) (int, error) {
	if _, err := w.file.Write(p); err != nil {
		return 0, err
	}
	if w.emit == nil {
		return len(p), nil
	}
	w.buf = append(w.buf, p...)
	for {
		i := bytes.IndexByte(w.buf, '\n')
		if i < 0 {
			break
		}
		w.send(string(w.buf[:i]))
		w.buf = w.buf[i+1:]
	}
	return len(p), nil
}

func (w *lineWriter) send(line string) {
	line = strings.TrimRight(line, "\r")
	if w.emitted == MaxLiveLines {
		w.emit(fmt.Sprintf("[depexit] live view truncated after %d lines; the full log is in the run's log file", MaxLiveLines))
	}
	w.emitted++
	if w.emitted <= MaxLiveLines {
		w.emit(line)
	}
}

func (w *lineWriter) flush() {
	if len(w.buf) > 0 && w.emit != nil {
		w.send(string(w.buf))
		w.buf = nil
	}
}

func dockerAvailable(ctx context.Context) bool {
	ctx, cancel := context.WithTimeout(ctx, 8*time.Second)
	defer cancel()
	return exec.CommandContext(ctx, "docker", "version", "--format", "{{.Server.Version}}").Run() == nil
}

func imageReady(ctx context.Context, image string) bool {
	ctx, cancel := context.WithTimeout(ctx, 8*time.Second)
	defer cancel()
	return exec.CommandContext(ctx, "docker", "image", "inspect", image).Run() == nil
}

// installFiles mirrors the AI scan: requirements.txt first, then other requirements*.txt.
func installFiles(repo string) []string {
	matches, _ := filepath.Glob(filepath.Join(repo, "requirements*.txt"))
	var names []string
	for _, m := range matches {
		names = append(names, filepath.Base(m))
	}
	sort.Slice(names, func(a, b int) bool {
		if (names[a] == "requirements.txt") != (names[b] == "requirements.txt") {
			return names[a] == "requirements.txt"
		}
		return names[a] < names[b]
	})
	return names
}

func shQuote(s string) string { return "'" + strings.ReplaceAll(s, "'", `'"'"'`) + "'" }

func buildInstallCommand(repoDir string) string {
	files := installFiles(repoDir)
	var reqArgs []string
	for _, f := range files {
		reqArgs = append(reqArgs, "-r", shQuote(f))
	}
	pipCmd := ""
	if len(reqArgs) > 0 {
		pipCmd = "/venv/bin/pip install --progress-bar off --disable-pip-version-check --no-input " + strings.Join(reqArgs, " ") + " && "
	} else if fileExists(filepath.Join(repoDir, "pyproject.toml")) || fileExists(filepath.Join(repoDir, "setup.py")) {
		pipCmd = "/venv/bin/pip install --progress-bar off --disable-pip-version-check --no-input . && "
	}
	return "python -m venv /venv && " + pipCmd + "(/venv/bin/python -c 'import pytest' 2>/dev/null || /venv/bin/pip install -q pytest)"
}

// dockerRun runs one container; on timeout it kills the container by name.
func (sb *Sandbox) dockerRun(ctx context.Context, name string, args []string, logPath string, emit func(string)) (int, error) {
	f, err := os.Create(logPath)
	if err != nil {
		return -1, err
	}
	defer f.Close()
	out := &lineWriter{file: f, emit: emit}
	defer out.flush()
	fmt.Fprintf(f, "$ docker %s\n", strings.Join(args, " "))
	ctx, cancel := context.WithTimeout(ctx, sb.Timeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, "docker", args...)
	cmd.Stdout, cmd.Stderr = out, out
	err = cmd.Run()
	if ctx.Err() == context.DeadlineExceeded {
		_ = exec.Command("docker", "kill", name).Run()
		fmt.Fprintf(out, "\n[depexit] timed out after %s\n", sb.Timeout)
		return -1, ctx.Err()
	}
	code := 0
	if err != nil {
		if ee, ok := err.(*exec.ExitError); ok {
			code = ee.ExitCode()
		} else {
			fmt.Fprintf(out, "\n[depexit] could not start docker: %v\n", err)
			return -1, err
		}
	}
	fmt.Fprintf(out, "exit code: %d\n", code)
	return code, nil
}

// Run installs the repo's requirements (network on) and runs pytest offline, writing logs + junit + result.json.
func (sb *Sandbox) Run(ctx context.Context, jobID, runID, kind, repoDir, runDir string) RunResult {
	start := time.Now()
	_ = os.MkdirAll(runDir, 0o755)
	res := RunResult{RunID: runID, Kind: kind, Image: sb.Image, StartedAt: start.UTC().Format(time.RFC3339)}
	finish := func() RunResult {
		res.DurationS = float64(time.Since(start).Milliseconds()) / 1000
		res.FinishedAt = time.Now().UTC().Format(time.RFC3339)
		b, _ := json.MarshalIndent(res, "", "  ")
		_ = os.WriteFile(filepath.Join(runDir, "result.json"), b, 0o644)
		return res
	}
	absRepo, _ := filepath.Abs(repoDir)
	volume := fmt.Sprintf("dx-%s-%s-venv", jobID, runID)
	defer exec.Command("docker", "volume", "rm", "-f", volume).Run()
	common := []string{"--memory", "2g", "--cpus", "2", "--pids-limit", "512", "--security-opt", "no-new-privileges",
		"--mount", "type=bind,source=" + absRepo + ",target=/work", "-v", volume + ":/venv", "-w", "/work"}

	emitFor := func(stream string) func(string) {
		if sb.OnLine == nil {
			return nil
		}
		return func(line string) { sb.OnLine(jobID, runID, stream, line) }
	}
	install := buildInstallCommand(repoDir)
	res.InstallCommand = []string{"sh", "-c", install}
	name := fmt.Sprintf("dx-%s-%s-install", jobID, runID)
	args := append([]string{"run", "--rm", "--name", name}, common...)
	args = append(args, sb.Image, "sh", "-c", install)
	if e := emitFor("install"); e != nil {
		e("$ " + install)
	}
	code, err := sb.dockerRun(ctx, name, args, filepath.Join(runDir, "install.log"), emitFor("install"))
	installCode := code
	res.InstallExitCode = &installCode
	if err == context.DeadlineExceeded {
		res.Status, res.Error = "timeout", "install timed out"
		return finish()
	}
	if err != nil {
		res.Status, res.Error = "error", err.Error()
		return finish()
	}
	if code != 0 {
		res.Status = "install_failed"
		_ = os.WriteFile(filepath.Join(runDir, "test.log"), []byte("[depexit] tests not run: dependency installation failed\n"), 0o644)
		return finish()
	}

	test := []string{"/venv/bin/python", "-m", "pytest", "-v", "-p", "no:cacheprovider", "-o", "addopts=",
		"--junitxml=.depexit/junit.xml"}
	res.Command = test
	name = fmt.Sprintf("dx-%s-%s-test", jobID, runID)
	args = append([]string{"run", "--rm", "--name", name, "--network", "none"}, common...)
	args = append(args, sb.Image, "sh", "-c", "mkdir -p .depexit && "+strings.Join(test, " "))
	if e := emitFor("test"); e != nil {
		e("$ " + strings.Join(test, " ") + "   (network disabled)")
	}
	code, err = sb.dockerRun(ctx, name, args, filepath.Join(runDir, "test.log"), emitFor("test"))
	testCode := code
	res.TestExitCode = &testCode
	copyFile(filepath.Join(repoDir, ".depexit", "junit.xml"), filepath.Join(runDir, "junit.xml"))
	switch {
	case err == context.DeadlineExceeded:
		res.Status, res.Error = "timeout", "tests timed out"
	case err != nil:
		res.Status, res.Error = "error", err.Error()
	case code == 0:
		res.Status = "passed"
	case code == 1 || code == 2:
		res.Status = "tests_failed"
	case code == 3 || code == 4:
		// internal error / conftest import failure: the code under test is broken, which is a test result
		res.Status, res.Error = "tests_failed", "test session failed to start (see test log)"
	case code == 5:
		res.Status, res.Error = "error", "no tests were collected"
	default:
		res.Status, res.Error = "error", fmt.Sprintf("pytest exited with code %d", code)
	}
	return finish()
}

func copyFile(src, dst string) {
	in, err := os.Open(src)
	if err != nil {
		return
	}
	defer in.Close()
	out, err := os.Create(dst)
	if err != nil {
		return
	}
	defer out.Close()
	_, _ = io.Copy(out, in)
}

// copyTree copies a repo, skipping VCS and cache directories.
func copyTree(src, dst string) error {
	return filepath.Walk(src, func(p string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		rel, _ := filepath.Rel(src, p)
		if info.IsDir() {
			switch info.Name() {
			case ".git", "__pycache__", ".depexit", ".venv", "node_modules":
				if rel != "." {
					return filepath.SkipDir
				}
			}
			return os.MkdirAll(filepath.Join(dst, rel), 0o755)
		}
		if !info.Mode().IsRegular() {
			return nil
		}
		copyFile(p, filepath.Join(dst, rel))
		return nil
	})
}

func runCmd(ctx context.Context, dir string, name string, args ...string) (string, error) {
	cmd := exec.CommandContext(ctx, name, args...)
	cmd.Dir = dir
	var buf bytes.Buffer
	cmd.Stdout, cmd.Stderr = &buf, &buf
	err := cmd.Run()
	return strings.TrimSpace(buf.String()), err
}
