package main

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestParseActionKeepsStartFlags(t *testing.T) {
	action, args := parseAction([]string{"--check", "--no-install"})
	if action != actionStart || len(args) != 2 || args[0] != "--check" {
		t.Fatalf("unexpected default action: %s %#v", action, args)
	}
	action, args = parseAction([]string{"status"})
	if action != actionStatus || len(args) != 0 {
		t.Fatalf("unexpected status action: %s %#v", action, args)
	}
}

func TestUpdateDotEnvPreservesCommentsAndUpdatesKeys(t *testing.T) {
	path := filepath.Join(t.TempDir(), ".env")
	if err := os.WriteFile(path, []byte("# keep\nLLM_MODEL=old\nOTHER=value\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := updateDotEnv(path, map[string]string{"LLM_MODEL": "new-model", "LLM_API_KEY": "secret"}); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	content := string(data)
	if !strings.Contains(content, "# keep") || !strings.Contains(content, "LLM_MODEL=new-model") || !strings.Contains(content, "LLM_API_KEY=secret") {
		t.Fatalf("unexpected .env content: %s", content)
	}
}

func TestSupervisorStateRoundTrip(t *testing.T) {
	path := filepath.Join(t.TempDir(), "supervisor.json")
	original := supervisorState{PID: 42, RootDir: "root", Services: map[string]int{"backend": 99}}
	data, err := json.Marshal(original)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, data, 0o600); err != nil {
		t.Fatal(err)
	}
	loaded, err := readSupervisorState(path)
	if err != nil || loaded.PID != 42 || loaded.Services["backend"] != 99 {
		t.Fatalf("unexpected state: %#v (%v)", loaded, err)
	}
}

func TestBuildRequired(t *testing.T) {
	t.Parallel()

	root := t.TempDir()
	output := filepath.Join(root, "dist", "main", "index.js")
	source := filepath.Join(root, "src", "main", "index.ts")
	mustWriteFile(t, output)
	mustWriteFile(t, source)

	base := time.Now().Add(-time.Minute)
	mustChtimes(t, source, base)
	mustChtimes(t, output, base.Add(time.Second))
	if buildRequired(output, []string{filepath.Join(root, "src")}) {
		t.Fatal("expected current build output to be reused")
	}

	mustChtimes(t, source, base.Add(2*time.Second))
	if !buildRequired(output, []string{filepath.Join(root, "src")}) {
		t.Fatal("expected newer source to require a rebuild")
	}
}

func TestQdrantAutoStartDefaultsToMemoryBackend(t *testing.T) {
	if qdrantAutoStartEnabled(map[string]string{"MEMORY_BACKEND": "sqlite"}) {
		t.Fatal("sqlite memory must not auto-start Qdrant")
	}
	if !qdrantAutoStartEnabled(map[string]string{"MEMORY_BACKEND": "qdrant"}) {
		t.Fatal("qdrant memory backend should opt into Qdrant auto-start")
	}
	if qdrantAutoStartEnabled(map[string]string{"MEMORY_BACKEND": "qdrant", "QDRANT_AUTO_START": "0"}) {
		t.Fatal("explicit QDRANT_AUTO_START=0 must disable auto-start")
	}
}

func TestMCPIsEnabledByDefault(t *testing.T) {
	if !mcpEnabled(map[string]string{}) {
		t.Fatal("the supervised launcher must start MCP unless explicitly disabled")
	}
	if mcpEnabled(map[string]string{"YUIZAKI_WITH_MCP": "0"}) {
		t.Fatal("YUIZAKI_WITH_MCP=0 must disable MCP startup")
	}
}

func TestPetReadyRequiresSuccessfulReadyState(t *testing.T) {
	t.Parallel()

	tests := []struct {
		name       string
		statusCode int
		body       string
		want       bool
	}{
		{name: "ready", statusCode: http.StatusOK, body: `{"ready":true}`, want: true},
		{name: "not ready", statusCode: http.StatusOK, body: `{"ready":false}`},
		{name: "invalid response", statusCode: http.StatusOK, body: `not-json`},
		{name: "request failed", statusCode: http.StatusServiceUnavailable, body: `{"ready":true}`},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
				w.WriteHeader(test.statusCode)
				_, _ = w.Write([]byte(test.body))
			}))
			defer server.Close()

			runner := &commandRunner{}
			if got := runner.petReady(context.Background(), server.URL, nil, time.Second); got != test.want {
				t.Fatalf("petReady() = %v, want %v", got, test.want)
			}
		})
	}
}

func TestBuildRequiredWhenOutputIsMissing(t *testing.T) {
	t.Parallel()

	root := t.TempDir()
	if !buildRequired(filepath.Join(root, "dist", "main", "index.js"), []string{filepath.Join(root, "src")}) {
		t.Fatal("expected a missing output to require a rebuild")
	}
}

func TestBuildFingerprintChangesWithContent(t *testing.T) {
	t.Parallel()

	root := t.TempDir()
	input := filepath.Join(root, "src", "main", "index.ts")
	mustWriteFile(t, input)
	first, err := buildFingerprint([]string{filepath.Join(root, "src")})
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(input, []byte("changed"), 0o644); err != nil {
		t.Fatal(err)
	}
	second, err := buildFingerprint([]string{filepath.Join(root, "src")})
	if err != nil {
		t.Fatal(err)
	}
	if first == second {
		t.Fatal("expected content changes to invalidate the build fingerprint")
	}
}

func TestBuildStateRoundTripAndReplacement(t *testing.T) {
	t.Parallel()

	statePath := filepath.Join(t.TempDir(), "dist", ".launcher-main-build.json")
	if err := writeBuildState(statePath, "input-first", "output-first"); err != nil {
		t.Fatal(err)
	}
	if !buildStateMatches(statePath, "input-first", "output-first") {
		t.Fatal("expected the persisted build state to match")
	}
	if err := writeBuildState(statePath, "input-second", "output-second"); err != nil {
		t.Fatal(err)
	}
	if !buildStateMatches(statePath, "input-second", "output-second") ||
		buildStateMatches(statePath, "input-first", "output-first") {
		t.Fatal("expected the build state to be replaced")
	}
}

func TestBuildIsCurrentRejectsMissingOrModifiedOutputs(t *testing.T) {
	t.Parallel()

	root := t.TempDir()
	input := filepath.Join(root, "src", "main", "index.ts")
	entry := filepath.Join(root, "dist", "main", "index.js")
	preload := filepath.Join(root, "dist", "preload", "index.js")
	statePath := filepath.Join(root, "dist", ".launcher-main-build.json")
	inputs := []string{filepath.Join(root, "src")}
	outputs := []string{filepath.Join(root, "dist", "main"), filepath.Join(root, "dist", "preload")}
	mustWriteFile(t, input)
	mustWriteFile(t, entry)
	mustWriteFile(t, preload)

	base := time.Now().Add(-time.Minute)
	mustChtimes(t, input, base)
	mustChtimes(t, entry, base.Add(time.Second))
	inputFingerprint, err := buildFingerprint(inputs)
	if err != nil {
		t.Fatal(err)
	}
	outputFingerprint, err := buildFingerprint(outputs)
	if err != nil {
		t.Fatal(err)
	}
	if err := writeBuildState(statePath, inputFingerprint, outputFingerprint); err != nil {
		t.Fatal(err)
	}
	if !buildIsCurrent(entry, statePath, inputs, outputs) {
		t.Fatal("expected an intact output tree to be current")
	}

	if err := os.Remove(preload); err != nil {
		t.Fatal(err)
	}
	if buildIsCurrent(entry, statePath, inputs, outputs) {
		t.Fatal("expected a missing non-entry output to require a rebuild")
	}

	if err := os.WriteFile(preload, []byte("modified"), 0o644); err != nil {
		t.Fatal(err)
	}
	if buildIsCurrent(entry, statePath, inputs, outputs) {
		t.Fatal("expected modified output content to require a rebuild")
	}
}

func mustWriteFile(t *testing.T, path string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("test"), 0o644); err != nil {
		t.Fatal(err)
	}
}

func mustChtimes(t *testing.T, path string, timestamp time.Time) {
	t.Helper()
	if err := os.Chtimes(path, timestamp, timestamp); err != nil {
		t.Fatal(err)
	}
}
