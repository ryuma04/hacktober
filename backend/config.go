package main

import (
	"bufio"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

// Config is read from the process environment overlaid on the repo-root .env file.
type Config struct {
	Root           string
	Port           string
	DataDir        string
	DatabaseURL    string
	JWTSecret      string
	AIServiceURL   string
	AllowedOrigins []string
	SandboxImage   string
	SandboxTimeout int
	DefaultRepoURL string
	PythonVersion  string
	// DemoStageDelay pauses each analysis stage (not the Docker runs) before it works, so a presenter can narrate a
	// fully cached run. 0 = off. Stage durations exclude the pause.
	DemoStageDelay time.Duration
}

func findRoot() string {
	dir, _ := os.Getwd()
	for d := dir; ; d = filepath.Dir(d) {
		if _, err := os.Stat(filepath.Join(d, ".env.example")); err == nil {
			return d
		}
		if filepath.Dir(d) == d {
			return dir
		}
	}
}

func loadDotEnv(path string) map[string]string {
	out := map[string]string{}
	f, err := os.Open(path)
	if err != nil {
		return out
	}
	defer f.Close()
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 1024*1024), 1024*1024)
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		k, v, ok := strings.Cut(line, "=")
		if ok {
			out[strings.TrimSpace(k)] = strings.Trim(strings.TrimSpace(v), `"'`)
		}
	}
	return out
}

func loadConfig() Config {
	root := findRoot()
	env := loadDotEnv(filepath.Join(root, ".env"))
	get := func(k, def string) string {
		if v := os.Getenv(k); v != "" {
			return v
		}
		if v := env[k]; v != "" {
			return v
		}
		return def
	}
	data := get("DATA_DIR", "./data")
	if !filepath.IsAbs(data) {
		data = filepath.Join(root, data)
	}
	_ = os.MkdirAll(data, 0o755)
	timeout, _ := strconv.Atoi(get("SANDBOX_TIMEOUT_S", "300"))
	var origins []string
	for _, o := range strings.Split(get("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173"), ",") {
		if o = strings.TrimSpace(o); o != "" {
			origins = append(origins, o)
		}
	}
	return Config{
		Root: root, Port: get("PORT", "8080"), DataDir: data,
		DatabaseURL:    get("DATABASE_URL", ""),
		JWTSecret:      get("JWT_SECRET", "default_jwt_secret_key_change_in_production"),
		AIServiceURL:   strings.TrimRight(get("AI_SERVICE_URL", "http://localhost:8001"), "/"),
		AllowedOrigins: origins, SandboxImage: get("SANDBOX_IMAGE", "python:3.12-slim"),
		SandboxTimeout: timeout, DefaultRepoURL: get("DEFAULT_REPO_URL", "https://github.com/rishrek/LinkWatch"),
		PythonVersion: get("PYTHON_VERSION", "3.12"),
		DemoStageDelay: func() time.Duration {
			s, _ := strconv.ParseFloat(get("DEMO_STAGE_DELAY_S", "0"), 64)
			if s < 0 || s > 30 {
				s = 0
			}
			return time.Duration(s * float64(time.Second))
		}(),
	}
}
