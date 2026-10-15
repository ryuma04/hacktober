package main

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"sort"
	"sync"
	"time"
)

var stageOrder = []struct{ ID, Label string }{
	{"clone", "Cloning repository"},
	{"scan", "Scanning dependencies"},
	{"usage", "Mapping usage"},
	{"propose", "Gemma 4: proposing replacements"},
	{"materialize", "Building migrated workspace"},
	{"sandbox_baseline", "Testing original dependencies"},
	{"sandbox_migrated", "Testing replacements"},
	{"compare", "Gemma 4: analysing gaps"},
	{"capsule", "Generating Exit Capsule"},
}

type Stage struct {
	ID         string     `json:"id"`
	Label      string     `json:"label"`
	Status     string     `json:"status"`
	StartedAt  *time.Time `json:"started_at,omitempty"`
	FinishedAt *time.Time `json:"finished_at,omitempty"`
	DurationS  float64    `json:"duration_s,omitempty"`
	Error      string     `json:"error,omitempty"`
}

type Options struct {
	IsolatedRuns    bool `json:"isolated_runs"`
	Repair          bool `json:"repair"`
	MaxDependencies int  `json:"max_dependencies"`
}

type Job struct {
	ID         string          `json:"id"`
	RepoURL    string          `json:"repo_url"`
	Ref        string          `json:"ref"`
	Commit     string          `json:"commit,omitempty"`
	Status     string          `json:"status"`
	CreatedAt  time.Time       `json:"created_at"`
	FinishedAt *time.Time      `json:"finished_at,omitempty"`
	Stages     []*Stage        `json:"stages"`
	Summary    json.RawMessage `json:"summary,omitempty"`
	Error      string          `json:"error,omitempty"`
	Options    Options         `json:"options"`
}

// Event is one SSE message; Data is merged with seq/ts/stage when serialised.
type Event struct {
	Type string         `json:"event"`
	Data map[string]any `json:"data"`
}

type jobState struct {
	job    *Job
	events []Event
	subs   map[chan Event]struct{}
}

type Store struct {
	mu   sync.Mutex
	dir  string
	jobs map[string]*jobState
}

func NewStore(dir string) *Store {
	s := &Store{dir: dir, jobs: map[string]*jobState{}}
	s.loadExisting()
	return s
}

func (s *Store) jobDir(id string) string { return filepath.Join(s.dir, id) }

func (s *Store) loadExisting() {
	entries, _ := os.ReadDir(s.dir)
	for _, e := range entries {
		b, err := os.ReadFile(filepath.Join(s.dir, e.Name(), "job.json"))
		if err != nil {
			continue
		}
		var j Job
		if json.Unmarshal(b, &j) != nil {
			continue
		}
		if j.Status == "running" || j.Status == "queued" {
			j.Status, j.Error = "failed", "server restarted while the analysis was running"
		}
		st := &jobState{job: &j, subs: map[chan Event]struct{}{}}
		if eb, err := os.ReadFile(filepath.Join(s.dir, e.Name(), "events.ndjson")); err == nil {
			for _, line := range splitLines(eb) {
				var ev Event
				if json.Unmarshal(line, &ev) == nil {
					st.events = append(st.events, ev)
				}
			}
		}
		s.jobs[j.ID] = st
	}
}

func splitLines(b []byte) [][]byte {
	var out [][]byte
	start := 0
	for i, c := range b {
		if c == '\n' {
			if i > start {
				out = append(out, b[start:i])
			}
			start = i + 1
		}
	}
	if start < len(b) {
		out = append(out, b[start:])
	}
	return out
}

func newID() string {
	b := make([]byte, 3)
	_, _ = rand.Read(b)
	return "dx_" + hex.EncodeToString(b)
}

func (s *Store) Create(repoURL, ref string, opts Options) *Job {
	j := &Job{ID: newID(), RepoURL: repoURL, Ref: ref, Status: "queued", CreatedAt: time.Now().UTC(), Options: opts}
	for _, st := range stageOrder {
		j.Stages = append(j.Stages, &Stage{ID: st.ID, Label: st.Label, Status: "pending"})
	}
	_ = os.MkdirAll(s.jobDir(j.ID), 0o755)
	s.mu.Lock()
	s.jobs[j.ID] = &jobState{job: j, subs: map[chan Event]struct{}{}}
	s.persistLocked(j.ID)
	s.mu.Unlock()
	return j
}

// Snapshot returns a deep copy safe to serialise outside the lock.
func (s *Store) Snapshot(id string) (*Job, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	st, ok := s.jobs[id]
	if !ok {
		return nil, false
	}
	b, _ := json.Marshal(st.job)
	var cp Job
	_ = json.Unmarshal(b, &cp)
	return &cp, true
}

func (s *Store) List() []*Job {
	s.mu.Lock()
	ids := make([]string, 0, len(s.jobs))
	for id := range s.jobs {
		ids = append(ids, id)
	}
	s.mu.Unlock()
	out := []*Job{}
	for _, id := range ids {
		if j, ok := s.Snapshot(id); ok {
			out = append(out, j)
		}
	}
	sort.Slice(out, func(a, b int) bool { return out[a].CreatedAt.After(out[b].CreatedAt) })
	return out
}

// Update mutates a job under the lock and persists it.
func (s *Store) Update(id string, fn func(j *Job)) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if st, ok := s.jobs[id]; ok {
		fn(st.job)
		s.persistLocked(id)
	}
}

func (s *Store) persistLocked(id string) {
	b, _ := json.MarshalIndent(s.jobs[id].job, "", "  ")
	tmp := filepath.Join(s.jobDir(id), "job.json.tmp")
	if os.WriteFile(tmp, b, 0o644) == nil {
		_ = os.Rename(tmp, filepath.Join(s.jobDir(id), "job.json"))
	}
}

// Emit appends an event (assigning seq/ts), persists it and fans it out to subscribers.
func (s *Store) Emit(id, typ string, data map[string]any) {
	if data == nil {
		data = map[string]any{}
	}
	s.mu.Lock()
	st, ok := s.jobs[id]
	if !ok {
		s.mu.Unlock()
		return
	}
	data["seq"] = len(st.events) + 1
	data["ts"] = time.Now().UTC().Format(time.RFC3339)
	ev := Event{Type: typ, Data: data}
	st.events = append(st.events, ev)
	if f, err := os.OpenFile(filepath.Join(s.jobDir(id), "events.ndjson"), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644); err == nil {
		b, _ := json.Marshal(ev)
		_, _ = f.Write(append(b, '\n'))
		_ = f.Close()
	}
	for ch := range st.subs {
		select {
		case ch <- ev:
		default: // slow subscriber: drop (it can re-sync by reconnecting; events replay)
		}
	}
	s.mu.Unlock()
}

// Subscribe returns past events and a channel for new ones.
func (s *Store) Subscribe(id string) ([]Event, chan Event, func(), bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	st, ok := s.jobs[id]
	if !ok {
		return nil, nil, nil, false
	}
	ch := make(chan Event, 256)
	st.subs[ch] = struct{}{}
	past := append([]Event(nil), st.events...)
	cancel := func() {
		s.mu.Lock()
		delete(st.subs, ch)
		s.mu.Unlock()
	}
	return past, ch, cancel, true
}
