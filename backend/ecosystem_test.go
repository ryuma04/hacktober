package main

import (
	"path/filepath"
	"testing"
)

func TestDetectEcosystem(t *testing.T) {
	cases := []struct {
		name  string
		files map[string]string
		want  string
	}{
		{"requirements", map[string]string{"requirements.txt": "toml\n"}, ecoPython},
		{"pyproject", map[string]string{"pyproject.toml": "[project]\n"}, ecoPython},
		{"python sources only", map[string]string{"src/app/main.py": "print(1)\n"}, ecoPython},
		{"npm only", map[string]string{"package.json": "{}", "src/main.jsx": "import React from 'react'\n"}, ecoNPM},
		{"mixed repo prefers python", map[string]string{"package.json": "{}", "requirements.txt": "flask\n"}, ecoPython},
		{"python inside node_modules does not count", map[string]string{"package.json": "{}", "node_modules/x/setup.py": ""}, ecoNPM},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			dir := t.TempDir()
			for p, content := range c.files {
				writeFile(t, filepath.Join(dir, filepath.FromSlash(p)), content)
			}
			if got := detectEcosystem(dir); got != c.want {
				t.Fatalf("detectEcosystem = %q, want %q", got, c.want)
			}
		})
	}
}
