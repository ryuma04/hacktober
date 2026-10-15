package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"
)

func TestStoreCreateAndSnapshot(t *testing.T) {
	tmpDir := t.TempDir()
	store := NewStore(tmpDir)

	job := store.Create("https://github.com/example/repo", "main", Options{MaxDependencies: 10})
	if job.ID == "" {
		t.Fatal("expected non-empty job ID")
	}
	if job.Status != "queued" {
		t.Fatalf("expected queued status, got %s", job.Status)
	}

	snap, ok := store.Snapshot(job.ID)
	if !ok {
		t.Fatal("expected job snapshot to exist")
	}
	if snap.RepoURL != "https://github.com/example/repo" {
		t.Fatalf("unexpected repo URL: %s", snap.RepoURL)
	}

	// Verify persistence file exists
	jobFile := filepath.Join(tmpDir, job.ID, "job.json")
	if _, err := os.Stat(jobFile); err != nil {
		t.Fatalf("job.json was not persisted: %v", err)
	}
}

func TestStoreConcurrentUpdates(t *testing.T) {
	tmpDir := t.TempDir()
	store := NewStore(tmpDir)
	job := store.Create("https://github.com/example/repo", "main", Options{})

	var wg sync.WaitGroup
	workers := 10
	iterations := 20

	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func(workerID int) {
			defer wg.Done()
			for j := 0; j < iterations; j++ {
				store.Update(job.ID, func(jObj *Job) {
					// safe mutation under lock
					jObj.Ref = "branch"
				})
				store.Emit(job.ID, "log", map[string]any{
					"worker": workerID,
					"iter":   j,
				})
			}
		}(i)
	}

	wg.Wait()

	snap, ok := store.Snapshot(job.ID)
	if !ok {
		t.Fatal("expected snapshot")
	}
	if snap.Ref != "branch" {
		t.Fatalf("expected ref branch, got %s", snap.Ref)
	}

	past, _, cancel, ok := store.Subscribe(job.ID)
	if !ok {
		t.Fatal("expected subscription")
	}
	defer cancel()

	expectedEvents := workers * iterations
	if len(past) != expectedEvents {
		t.Fatalf("expected %d events, got %d", expectedEvents, len(past))
	}
}

func TestStoreRestartRecovery(t *testing.T) {
	tmpDir := t.TempDir()
	store1 := NewStore(tmpDir)

	j1 := store1.Create("https://github.com/example/running", "main", Options{})
	store1.Update(j1.ID, func(j *Job) {
		j.Status = "running"
	})

	j2 := store1.Create("https://github.com/example/completed", "main", Options{})
	store1.Update(j2.ID, func(j *Job) {
		j.Status = "completed"
		j.Summary = json.RawMessage(`{"dependencies_total": 5, "at_risk": 2}`)
	})

	// Simulate restart by initializing a second store pointing to the same directory
	store2 := NewStore(tmpDir)

	recoveredRunning, ok := store2.Snapshot(j1.ID)
	if !ok {
		t.Fatal("expected j1 to be loaded on restart")
	}
	// Per architecture and store.go line 93-95, running jobs must be transitioned to failed on restart
	if recoveredRunning.Status != "failed" {
		t.Fatalf("expected running job to recover as failed on restart, got %s", recoveredRunning.Status)
	}
	if recoveredRunning.Error == "" {
		t.Fatal("expected error message describing restart failure")
	}

	recoveredCompleted, ok := store2.Snapshot(j2.ID)
	if !ok {
		t.Fatal("expected j2 to be loaded on restart")
	}
	if recoveredCompleted.Status != "completed" {
		t.Fatalf("expected completed job status preserved, got %s", recoveredCompleted.Status)
	}
}

func TestStoreSubscriptionAndEventOrdering(t *testing.T) {
	tmpDir := t.TempDir()
	store := NewStore(tmpDir)
	job := store.Create("https://github.com/example/repo", "main", Options{})

	store.Emit(job.ID, "job_started", map[string]any{"step": 1})

	past, ch, cancel, ok := store.Subscribe(job.ID)
	if !ok {
		t.Fatal("expected subscribe to succeed")
	}
	defer cancel()

	if len(past) != 1 {
		t.Fatalf("expected 1 past event, got %d", len(past))
	}
	if past[0].Type != "job_started" {
		t.Fatalf("unexpected past event type: %s", past[0].Type)
	}

	// Emit new event while subscribed
	store.Emit(job.ID, "stage_started", map[string]any{"stage": "scan"})

	select {
	case ev := <-ch:
		if ev.Type != "stage_started" {
			t.Fatalf("expected stage_started event, got %s", ev.Type)
		}
		if ev.Data["seq"].(int) != 2 {
			t.Fatalf("expected sequence 2, got %v", ev.Data["seq"])
		}
	case <-time.After(1 * time.Second):
		t.Fatal("timed out waiting for emitted event on subscriber channel")
	}
}

func TestStoreFlatEventsRoundtrip(t *testing.T) {
	tmpDir := t.TempDir()
	jobID := "dx_flat01"
	jobDir := filepath.Join(tmpDir, jobID)
	_ = os.MkdirAll(jobDir, 0o755)

	// Write a job.json
	jobData := `{"id":"dx_flat01","repo_url":"https://github.com/example/flat","ref":"main","status":"completed","created_at":"2026-10-15T10:00:00Z","stages":[]}`
	_ = os.WriteFile(filepath.Join(jobDir, "job.json"), []byte(jobData), 0o644)

	// Write flat events like in fixtures/events.ndjson
	eventsNDJSON := `{"event":"job_started","seq":1,"ts":"2026-10-15T10:00:00Z","repo_url":"https://github.com/example/flat"}` + "\n" +
		`{"event":"stage_started","seq":2,"ts":"2026-10-15T10:00:01Z","stage":"scan"}` + "\n" +
		`{"event":"log","seq":3,"ts":"2026-10-15T10:00:02Z","stage":"scan","level":"info","message":"test message"}` + "\n"

	_ = os.WriteFile(filepath.Join(jobDir, "events.ndjson"), []byte(eventsNDJSON), 0o644)

	store := NewStore(tmpDir)
	past, _, cancel, ok := store.Subscribe(jobID)
	if !ok {
		t.Fatal("expected subscription to succeed")
	}
	defer cancel()

	if len(past) != 3 {
		t.Fatalf("expected 3 events loaded, got %d", len(past))
	}

	// Verify Data is populated and not nil
	if past[0].Type != "job_started" || past[0].Data["repo_url"] != "https://github.com/example/flat" {
		t.Fatalf("expected job_started event data populated, got: %+v", past[0])
	}
	if past[1].Type != "stage_started" || past[1].Data["stage"] != "scan" {
		t.Fatalf("expected stage_started event data populated, got: %+v", past[1])
	}
	if past[2].Type != "log" || past[2].Data["message"] != "test message" {
		t.Fatalf("expected log message populated, got: %+v", past[2])
	}
}

