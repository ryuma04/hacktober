package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestBuildInstallCommandWithRequirements(t *testing.T) {
	tmpDir := t.TempDir()
	_ = os.WriteFile(filepath.Join(tmpDir, "requirements.txt"), []byte("requests==2.28.0\n"), 0o644)
	_ = os.WriteFile(filepath.Join(tmpDir, "requirements-dev.txt"), []byte("pytest>=7.0.0\n"), 0o644)

	cmd := buildInstallCommand(tmpDir)

	if !strings.Contains(cmd, "python -m venv /venv") {
		t.Fatalf("expected venv creation: %s", cmd)
	}
	if !strings.Contains(cmd, "-r 'requirements.txt'") {
		t.Fatalf("expected requirements.txt install: %s", cmd)
	}
	if !strings.Contains(cmd, "-r 'requirements-dev.txt'") {
		t.Fatalf("expected requirements-dev.txt install: %s", cmd)
	}
	if !strings.Contains(cmd, "pytest") {
		t.Fatalf("expected pytest check: %s", cmd)
	}
}

func TestBuildInstallCommandWithPyprojectOnly(t *testing.T) {
	tmpDir := t.TempDir()
	_ = os.WriteFile(filepath.Join(tmpDir, "pyproject.toml"), []byte("[project]\nname='demo'\n"), 0o644)

	cmd := buildInstallCommand(tmpDir)

	// Must install with . instead of empty requirement list
	if !strings.Contains(cmd, "pip install -q --disable-pip-version-check --no-input .") {
		t.Fatalf("expected pip install . for pyproject-only repo, got: %s", cmd)
	}
	if strings.Contains(cmd, "--no-input  &&") {
		t.Fatalf("must not contain empty requirement argument, got: %s", cmd)
	}
}

func TestBuildInstallCommandZeroDependencies(t *testing.T) {
	tmpDir := t.TempDir()
	_ = os.WriteFile(filepath.Join(tmpDir, "main.py"), []byte("print('hello')\n"), 0o644)

	cmd := buildInstallCommand(tmpDir)

	// Must create venv and install pytest without crashing on empty requirements
	if strings.Contains(cmd, "--no-input  &&") {
		t.Fatalf("must not contain empty requirement argument, got: %s", cmd)
	}
	if !strings.Contains(cmd, "python -m venv /venv") || !strings.Contains(cmd, "pytest") {
		t.Fatalf("expected venv and pytest setup, got: %s", cmd)
	}
}
