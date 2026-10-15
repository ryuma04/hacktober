package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

type AIClient struct {
	base string
	http *http.Client
}

func NewAIClient(base string) *AIClient {
	return &AIClient{base: base, http: &http.Client{}}
}

// Call POSTs to the AI service and returns the decoded JSON object.
func (c *AIClient) Call(ctx context.Context, path string, body any, timeout time.Duration) (map[string]any, error) {
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	b, _ := json.Marshal(body)
	req, _ := http.NewRequestWithContext(ctx, http.MethodPost, c.base+path, bytes.NewReader(b))
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.http.Do(req)
	if err != nil {
		return nil, fmt.Errorf("AI service %s: %w", path, err)
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)
	var out map[string]any
	if err := json.Unmarshal(raw, &out); err != nil {
		return nil, fmt.Errorf("AI service %s: invalid JSON (HTTP %d)", path, resp.StatusCode)
	}
	if resp.StatusCode >= 300 {
		if e, ok := out["error"].(map[string]any); ok {
			return nil, fmt.Errorf("AI service %s: %v", path, e["message"])
		}
		return nil, fmt.Errorf("AI service %s: HTTP %d", path, resp.StatusCode)
	}
	return out, nil
}

func (c *AIClient) Health(ctx context.Context) (map[string]any, bool) {
	ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	req, _ := http.NewRequestWithContext(ctx, http.MethodGet, c.base+"/v1/health", nil)
	resp, err := c.http.Do(req)
	if err != nil {
		return nil, false
	}
	defer resp.Body.Close()
	var out map[string]any
	if json.NewDecoder(resp.Body).Decode(&out) != nil {
		return nil, false
	}
	return out, resp.StatusCode == 200
}
