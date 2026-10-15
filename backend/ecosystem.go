package main

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
)

// Ecosystems DepExit understands. Python gets the full pipeline (migration + Docker verification);
// npm is scan-only for now (risks, usage, blast radius and Gemma 4 proposals, no migration or sandbox runs).
const (
	ecoPython = "python"
	ecoNPM    = "npm"
)

// errScanOnly marks the deliberate end of the analysis lane for scan-only ecosystems (not a failure).
var errScanOnly = errors.New(scanOnlyReason)

const scanOnlyReason = "scan-only for npm projects: migration and Docker verification are Python-only for now"

// detectEcosystem picks the project's ecosystem from what is in the clone. Python wins for mixed repositories
// (its pipeline is complete); a repository with only package.json is treated as npm.
func detectEcosystem(repo string) string {
	for _, m := range []string{"pyproject.toml", "setup.py", "setup.cfg", "Pipfile"} {
		if fileExists(filepath.Join(repo, m)) {
			return ecoPython
		}
	}
	if reqs, _ := filepath.Glob(filepath.Join(repo, "requirements*.txt")); len(reqs) > 0 {
		return ecoPython
	}
	if hasPythonSource(repo, 3) {
		return ecoPython
	}
	if fileExists(filepath.Join(repo, "package.json")) {
		return ecoNPM
	}
	return ecoPython
}

func hasPythonSource(dir string, depth int) bool {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return false
	}
	for _, e := range entries {
		name := e.Name()
		if e.IsDir() {
			if depth > 0 && !strings.HasPrefix(name, ".") && name != "node_modules" && name != "venv" && hasPythonSource(filepath.Join(dir, name), depth-1) {
				return true
			}
			continue
		}
		if strings.HasSuffix(name, ".py") {
			return true
		}
	}
	return false
}
