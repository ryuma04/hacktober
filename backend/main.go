// DepExit API server: orchestrates the analysis pipeline, runs the Docker sandbox and serves results.
// See docs/ARCHITECTURE.md and docs/API_CONTRACT.md.
package main

import (
	"context"
	"log"
	"net/http"
	"os/exec"
	"time"
)

func main() {
	cfg := loadConfig()
	store := NewStore(cfg.DataDir)
	pipe := &Pipeline{cfg: cfg, store: store, ai: NewAIClient(cfg.AIServiceURL),
		sb: &Sandbox{Image: cfg.SandboxImage, Timeout: time.Duration(cfg.SandboxTimeout) * time.Second,
			OnLine: func(jobID, runID, stream, line string) {
				store.Emit(jobID, "sandbox_log", map[string]any{"run": runID, "stream": stream, "line": line})
			}}}
	var authDB *AuthDB
	if cfg.DatabaseURL != "" {
		db, err := InitAuthDB(cfg.DatabaseURL)
		if err != nil {
			log.Printf("[Neon DB Warning] Failed to connect: %v", err)
		} else {
			authDB = db
		}
	} else {
		log.Printf("[Neon DB] DATABASE_URL not set; authentication endpoints will be inactive")
	}

	api := &API{cfg: cfg, store: store, pipe: pipe, authDB: authDB}

	go func() { // pre-pull the sandbox image so the first analysis is fast
		ctx := context.Background()
		if dockerAvailable(ctx) && !imageReady(ctx, cfg.SandboxImage) {
			log.Printf("pulling %s ...", cfg.SandboxImage)
			if err := exec.Command("docker", "pull", cfg.SandboxImage).Run(); err != nil {
				log.Printf("docker pull failed: %v", err)
			}
		}
	}()

	log.Printf("DepExit API on :%s (data %s, AI service %s)", cfg.Port, cfg.DataDir, cfg.AIServiceURL)
	srv := &http.Server{Addr: ":" + cfg.Port, Handler: api.routes(), ReadHeaderTimeout: 10 * time.Second}
	log.Fatal(srv.ListenAndServe())
}
