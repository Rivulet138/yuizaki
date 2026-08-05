package main

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

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
