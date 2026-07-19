package main

import (
	"bufio"
	"bytes"
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"syscall"
	"time"
)

const (
	defaultBackendPort  = "8001"
	defaultControlPort  = "38945"
	defaultRendererPort = "5173"
	defaultMCPPort      = "7777"
)

type launcherConfig struct {
	rootDir          string
	pythonDir        string
	electronDir      string
	nodeMCPDir       string
	scriptsDir       string
	logDir           string
	backendURL       string
	controlURL       string
	rendererOrigin   string
	rendererURL      string
	panelOpenURL     string
	mcpURL           string
	withMCP          bool
	devRenderer      bool
	noOpen           bool
	noShowPet        bool
	noQdrant         bool
	smoke            bool
	checkOnly        bool
	serverHost       string
	serverPort       string
	serverFallbacks  string
	controlPort      string
	controlFallbacks string
	rendererPort     string
	renderFallbacks  string
	mcpPort          string
	token            string
	env              map[string]string
	logger           *logHub
}

type commandRunner struct {
	cfg      *launcherConfig
	mu       sync.Mutex
	services []*serviceProcess
}

type serviceProcess struct {
	name    string
	cmd     *exec.Cmd
	done    chan error
	stopped bool
}

type logHub struct {
	mu    sync.Mutex
	file  *os.File
	files map[string]*os.File
}

func main() {
	cfg, err := newConfig()
	if err != nil {
		fmt.Fprintf(os.Stderr, "[launcher] %v\n", err)
		os.Exit(1)
	}
	defer cfg.logger.Close()

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	runner := &commandRunner{cfg: cfg}
	go func() {
		<-ctx.Done()
		cfg.logger.Log("launcher", "shutdown requested; stopping supervised services")
		runner.StopAll()
	}()

	if err := runner.Run(ctx); err != nil {
		cfg.logger.Log("launcher", "startup failed: "+err.Error())
		runner.StopAll()
		os.Exit(1)
	}
}

func newConfig() (*launcherConfig, error) {
	exePath, err := os.Executable()
	if err != nil {
		return nil, err
	}
	rootDir := filepath.Dir(exePath)
	if _, err := os.Stat(filepath.Join(rootDir, "start.bat")); err != nil {
		cwd, cwdErr := os.Getwd()
		if cwdErr == nil {
			rootDir = cwd
		}
	}
	rootDir, err = filepath.Abs(rootDir)
	if err != nil {
		return nil, err
	}

	cfg := &launcherConfig{
		rootDir:          rootDir,
		pythonDir:        filepath.Join(rootDir, "python"),
		electronDir:      filepath.Join(rootDir, "electron"),
		nodeMCPDir:       filepath.Join(rootDir, "node-mcp"),
		scriptsDir:       filepath.Join(rootDir, "scripts"),
		logDir:           filepath.Join(rootDir, "logs", "dev"),
		withMCP:          true,
		devRenderer:      true,
		serverHost:       envOr("SERVER_HOST", "127.0.0.1"),
		serverPort:       envOr("SERVER_PORT", defaultBackendPort),
		serverFallbacks:  envOr("SERVER_PORT_FALLBACKS", "8011,8012,8013,8014,8015,8021,8022"),
		controlPort:      envOr("CONTROL_SERVER_PORT", defaultControlPort),
		controlFallbacks: envOr("CONTROL_SERVER_PORT_FALLBACKS", "38946,38947,38948,38949"),
		rendererPort:     envOr("RENDERER_PORT", defaultRendererPort),
		renderFallbacks:  envOr("RENDERER_PORT_FALLBACKS", "5174,5175,5176,5177"),
		mcpPort:          envOr("MCP_PORT", defaultMCPPort),
		env:              envMap(),
	}

	flagSet := flag.NewFlagSet(filepath.Base(os.Args[0]), flag.ExitOnError)
	flagSet.BoolVar(&cfg.withMCP, "with-mcp", true, "start MCP service")
	flagSet.BoolVar(&cfg.noOpen, "no-open", false, "do not open the panel URL")
	flagSet.BoolVar(&cfg.noShowPet, "no-show-pet", false, "do not restore the desktop pet layer")
	flagSet.BoolVar(&cfg.noQdrant, "no-qdrant", false, "skip Qdrant Docker auto-start")
	flagSet.BoolVar(&cfg.smoke, "smoke", false, "run lightweight smoke checks after startup")
	flagSet.BoolVar(&cfg.checkOnly, "check", false, "run startup preflight checks only")
	noMCP := flagSet.Bool("no-mcp", false, "do not start MCP service")
	noDevRenderer := flagSet.Bool("no-dev-renderer", false, "serve built renderer through Electron control server")
	devRenderer := flagSet.Bool("dev-renderer", true, "start Vite dev renderer")
	if err := flagSet.Parse(os.Args[1:]); err != nil {
		return nil, err
	}
	if *noMCP {
		cfg.withMCP = false
	}
	if *noDevRenderer {
		cfg.devRenderer = false
	} else {
		cfg.devRenderer = *devRenderer
	}
	if envOr("QDRANT_AUTO_START", "") == "0" {
		cfg.noQdrant = true
	}

	if err := os.MkdirAll(cfg.logDir, 0o755); err != nil {
		return nil, err
	}
	logger, err := newLogHub(cfg.logDir)
	if err != nil {
		return nil, err
	}
	cfg.logger = logger

	cfg.token = cfg.env["YUIZAKI_CONTROL_TOKEN"]
	if cfg.token == "" {
		cfg.token = cfg.env["YUIZAKI_BACKEND_API_TOKEN"]
	}
	if cfg.token == "" {
		token, err := generateToken()
		if err != nil {
			return nil, err
		}
		cfg.token = token
	}
	cfg.env["YUIZAKI_CONTROL_TOKEN"] = cfg.token
	cfg.env["YUIZAKI_BACKEND_API_TOKEN"] = cfg.token
	cfg.env["YUIZAKI_SUPERVISOR"] = "1"
	cfg.env["APP_ENV"] = envOrMap(cfg.env, "APP_ENV", "development")
	cfg.env["ENV"] = envOrMap(cfg.env, "ENV", "development")
	cfg.env["NODE_ENV"] = envOrMap(cfg.env, "NODE_ENV", "development")
	cfg.env["SCHEMA_MIGRATION_MODE"] = envOrMap(cfg.env, "SCHEMA_MIGRATION_MODE", "bootstrap")
	cfg.env["SERVER_HOST"] = cfg.serverHost
	cfg.env["SERVER_BIND_HOST"] = envOrMap(cfg.env, "SERVER_BIND_HOST", "127.0.0.1")
	cfg.env["SERVER_DEBUG"] = envOrMap(cfg.env, "SERVER_DEBUG", "true")
	cfg.env["LOG_LEVEL"] = envOrMap(cfg.env, "LOG_LEVEL", "INFO")
	cfg.env["MAX_BACKEND_WAIT_SECONDS"] = envOrMap(cfg.env, "MAX_BACKEND_WAIT_SECONDS", "120")
	cfg.env["MAX_CONTROL_WAIT_SECONDS"] = envOrMap(cfg.env, "MAX_CONTROL_WAIT_SECONDS", "240")
	cfg.env["PYTHONUNBUFFERED"] = envOrMap(cfg.env, "PYTHONUNBUFFERED", "1")
	cfg.env["PYTHONIOENCODING"] = envOrMap(cfg.env, "PYTHONIOENCODING", "utf-8")
	cfg.env["DESKTOP_PET_SKIP_INTERNAL_PYTHON"] = "1"
	cfg.env["YUIZAKI_ELECTRON_ROOT"] = cfg.electronDir
	cfg.env["ELECTRON_RUN_AS_NODE"] = ""
	cfg.refreshURLs()

	return cfg, nil
}

func (r *commandRunner) Run(ctx context.Context) error {
	cfg := r.cfg
	cfg.logger.Log("launcher", "Yuizaki supervised startup initialized")
	cfg.logger.Log("launcher", "Project root: "+cfg.rootDir)
	cfg.logger.Log("launcher", fmt.Sprintf("Mode: devRenderer=%t withMCP=%t", cfg.devRenderer, cfg.withMCP))

	if err := r.preflight(ctx); err != nil {
		return err
	}
	if cfg.checkOnly {
		cfg.logger.Log("launcher", "preflight check passed")
		return nil
	}
	if err := r.selectControlAndRendererPorts(ctx); err != nil {
		return err
	}
	if err := r.buildElectron(ctx); err != nil {
		return err
	}
	r.prepareModelCaches()
	if !cfg.noQdrant {
		if err := r.ensureQdrant(ctx); err != nil {
			return err
		}
	} else {
		cfg.logger.Log("launcher", "Qdrant Docker check skipped")
	}
	backendAlreadyRunning, err := r.selectAndCheckBackend(ctx)
	if err != nil {
		return err
	}
	if !backendAlreadyRunning {
		r.checkDatabaseMigrations(ctx)
		if err := r.startBackend(ctx); err != nil {
			return err
		}
		if err := r.waitHTTP(ctx, "backend", cfg.backendURL+"/api/ping", nil, 120*time.Second); err != nil {
			return err
		}
	} else {
		cfg.logger.Log("launcher", "Reusing existing backend on "+cfg.backendURL)
	}
	if cfg.withMCP {
		if err := r.ensureMCP(ctx); err != nil {
			return err
		}
	}
	if cfg.devRenderer {
		if err := r.ensureRenderer(ctx); err != nil {
			return err
		}
	}
	if err := r.startElectron(ctx); err != nil {
		return err
	}
	if err := r.waitHTTP(ctx, "control", cfg.controlURL+"/api/health", nil, 240*time.Second); err != nil {
		return err
	}
	if err := r.verifyControlBackend(ctx); err != nil {
		return err
	}
	if cfg.smoke {
		if err := r.smoke(ctx); err != nil {
			return err
		}
	}
	if !cfg.noShowPet {
		if err := r.ensurePetVisible(ctx); err != nil {
			cfg.logger.Log("launcher", "pet restore warning: "+err.Error())
		}
	}
	if !cfg.noOpen {
		r.openPanel()
	}

	cfg.logger.Log("launcher", "============================================")
	cfg.logger.Log("launcher", "Yuizaki supervised launch completed")
	cfg.logger.Log("launcher", "Backend  : "+cfg.backendURL)
	cfg.logger.Log("launcher", "Renderer : "+cfg.rendererURL)
	cfg.logger.Log("launcher", "Control  : "+cfg.controlURL+"/")
	cfg.logger.Log("launcher", "Logs     : "+cfg.logDir)
	cfg.logger.Log("launcher", "Press Ctrl+C to stop supervised services.")

	return r.monitor(ctx)
}

func (r *commandRunner) preflight(ctx context.Context) error {
	args := []string{"/d", "/c", "call", filepath.Join(r.cfg.rootDir, "start.bat"), "--check", "--no-pause", "--no-open", "--no-show-pet"}
	if r.cfg.withMCP {
		args = append(args, "--with-mcp")
	} else {
		args = append(args, "--no-mcp")
	}
	if r.cfg.devRenderer {
		args = append(args, "--dev-renderer")
	} else {
		args = append(args, "--no-dev-renderer")
	}
	if r.cfg.noQdrant {
		args = append(args, "--no-qdrant")
	}
	return r.runLogged(ctx, "preflight", r.cfg.rootDir, "cmd.exe", args...)
}

func (r *commandRunner) selectControlAndRendererPorts(ctx context.Context) error {
	controlPort, status, err := r.selectPort(ctx, "control", r.cfg.controlPort, r.cfg.controlFallbacks)
	if err != nil {
		return err
	}
	if status == "blocked" {
		return fmt.Errorf("control ports are occupied; preferred=%s", r.cfg.controlPort)
	}
	r.cfg.controlPort = controlPort
	r.cfg.logger.Log("launcher", fmt.Sprintf("Control port selected: %s (%s)", controlPort, status))
	if r.cfg.devRenderer {
		rendererPort, rendererStatus, err := r.selectPort(ctx, "renderer", r.cfg.rendererPort, r.cfg.renderFallbacks)
		if err != nil {
			return err
		}
		if rendererStatus == "blocked" {
			return fmt.Errorf("renderer ports are occupied; preferred=%s", r.cfg.rendererPort)
		}
		r.cfg.rendererPort = rendererPort
		r.cfg.logger.Log("launcher", fmt.Sprintf("Renderer port selected: %s (%s)", rendererPort, rendererStatus))
	}
	r.cfg.refreshURLs()
	return nil
}

func (r *commandRunner) selectAndCheckBackend(ctx context.Context) (bool, error) {
	port, status, err := r.selectPort(ctx, "backend", r.cfg.serverPort, r.cfg.serverFallbacks)
	if err != nil {
		return false, err
	}
	if status == "blocked" {
		return false, fmt.Errorf("backend ports are occupied; preferred=%s", r.cfg.serverPort)
	}
	r.cfg.serverPort = port
	r.cfg.refreshURLs()
	r.cfg.logger.Log("launcher", fmt.Sprintf("Backend port selected: %s (%s)", port, status))
	if status == "healthy" {
		return true, nil
	}
	ok := r.httpOK(ctx, r.cfg.backendURL+"/api/ping", nil, 5*time.Second)
	if ok {
		return true, nil
	}
	return false, nil
}

func (r *commandRunner) selectPort(ctx context.Context, mode, preferred, fallbacks string) (string, string, error) {
	out, err := r.runCapture(ctx, "port-"+mode, r.cfg.rootDir, "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", filepath.Join(r.cfg.scriptsDir, "select_startup_port.ps1"), "-Mode", mode, "-PreferredPort", preferred, "-FallbackPorts", fallbacks, "-ProjectRoot", r.cfg.rootDir)
	if err != nil {
		return "", "", err
	}
	line := firstNonEmptyLine(out)
	parts := strings.SplitN(line, "|", 2)
	if len(parts) != 2 {
		return "", "", fmt.Errorf("unexpected port selection output for %s: %q", mode, line)
	}
	return strings.TrimSpace(parts[0]), strings.TrimSpace(parts[1]), nil
}

func (r *commandRunner) buildElectron(ctx context.Context) error {
	script := "npm run build:electron"
	if !r.cfg.devRenderer {
		script = "npm run build"
	}
	return r.runLogged(ctx, "build", r.cfg.electronDir, "cmd.exe", "/d", "/c", script)
}

func (r *commandRunner) prepareModelCaches() {
	cacheDirs := []string{
		filepath.Join(r.cfg.pythonDir, ".cache", "huggingface"),
		filepath.Join(r.cfg.pythonDir, ".cache", "modelscope"),
		filepath.Join(r.cfg.pythonDir, ".cache", "GenieData", "GenieData"),
	}
	for _, dir := range cacheDirs {
		_ = os.MkdirAll(dir, 0o755)
	}
	r.cfg.env["HF_HOME"] = cacheDirs[0]
	r.cfg.env["SENTENCE_TRANSFORMERS_HOME"] = cacheDirs[0]
	r.cfg.env["MODELSCOPE_CACHE"] = cacheDirs[1]
	r.cfg.env["GENIE_DATA_DIR"] = cacheDirs[2]
	r.cfg.logger.Log("launcher", "Model cache directories prepared")
}

func (r *commandRunner) ensureQdrant(ctx context.Context) error {
	return r.runLogged(ctx, "qdrant", r.cfg.rootDir, "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", filepath.Join(r.cfg.scriptsDir, "ensure_qdrant_docker.ps1"), "-ProjectRoot", r.cfg.rootDir, "-SettingsPath", filepath.Join(r.cfg.pythonDir, "config", "settings.json"), "-EnvPath", filepath.Join(r.cfg.pythonDir, ".env"))
}

func (r *commandRunner) checkDatabaseMigrations(ctx context.Context) {
	pythonExe := filepath.Join(r.cfg.pythonDir, ".venv", "Scripts", "python.exe")
	err := r.runLogged(ctx, "migration-check", r.cfg.pythonDir, pythonExe, "migration_check.py")
	if err != nil {
		r.cfg.logger.Log("migration-check", "schema is not at Alembic head; backend runner will auto-migrate on startup")
	}
}

func (r *commandRunner) startBackend(ctx context.Context) error {
	return r.startService(ctx, "backend", r.cfg.pythonDir, "cmd.exe", "/d", "/c", "call", filepath.Join(r.cfg.scriptsDir, "run_backend_dev.bat"))
}

func (r *commandRunner) ensureMCP(ctx context.Context) error {
	if r.httpOK(ctx, r.cfg.mcpURL+"/health", nil, 3*time.Second) {
		r.cfg.logger.Log("mcp", "Reusing existing MCP service: "+r.cfg.mcpURL)
		return nil
	}
	if err := r.startService(ctx, "mcp", r.cfg.nodeMCPDir, "cmd.exe", "/d", "/c", "call", filepath.Join(r.cfg.scriptsDir, "run_mcp_dev.bat")); err != nil {
		return err
	}
	return r.waitHTTP(ctx, "mcp", r.cfg.mcpURL+"/health", nil, 120*time.Second)
}

func (r *commandRunner) ensureRenderer(ctx context.Context) error {
	if r.httpOK(ctx, r.cfg.rendererURL, nil, 2*time.Second) {
		r.cfg.logger.Log("renderer", "Reusing existing renderer: "+r.cfg.rendererURL)
		return nil
	}
	if err := r.startService(ctx, "renderer", r.cfg.electronDir, "cmd.exe", "/d", "/c", "call", filepath.Join(r.cfg.scriptsDir, "run_renderer_dev.bat")); err != nil {
		return err
	}
	return r.waitHTTP(ctx, "renderer", r.cfg.rendererURL, nil, 120*time.Second)
}

func (r *commandRunner) startElectron(ctx context.Context) error {
	return r.startService(ctx, "electron", r.cfg.electronDir, "cmd.exe", "/d", "/c", "call", filepath.Join(r.cfg.scriptsDir, "run_electron_app.bat"))
}

func (r *commandRunner) verifyControlBackend(ctx context.Context) error {
	headers := r.authHeaders()
	return r.waitHTTP(ctx, "control-backend", r.cfg.controlURL+"/api/ping", headers, 45*time.Second)
}

func (r *commandRunner) smoke(ctx context.Context) error {
	headers := r.authHeaders()
	paths := []string{"/api/ping", "/health", "/api/readiness", "/api/companions", "/api/pet/state", "/api/pet/catalog"}
	for _, path := range paths {
		if err := r.waitHTTP(ctx, "smoke", r.cfg.controlURL+path, headers, 30*time.Second); err != nil {
			return err
		}
	}
	return nil
}

func (r *commandRunner) ensurePetVisible(ctx context.Context) error {
	headers := r.authHeaders()
	posts := []struct {
		path string
		body map[string]any
	}{
		{"/api/pet/visibility", map[string]any{"visible": true}},
		{"/api/pet/opacity", map[string]any{"opacity": 1}},
		{"/api/pet/scale", map[string]any{"scale": 0.32}},
		{"/api/pet/dock", map[string]any{}},
	}
	for _, post := range posts {
		if err := r.postJSON(ctx, r.cfg.controlURL+post.path, headers, post.body, 8*time.Second); err != nil {
			return err
		}
	}
	r.cfg.logger.Log("launcher", "Desktop pet layer restore commands sent")
	return nil
}

func (r *commandRunner) openPanel() {
	if err := exec.Command("cmd.exe", "/d", "/c", "start", "", r.cfg.panelOpenURL).Start(); err != nil {
		r.cfg.logger.Log("launcher", "failed to open panel: "+err.Error())
	}
}

func (r *commandRunner) monitor(ctx context.Context) error {
	done := make(chan string)
	r.mu.Lock()
	services := append([]*serviceProcess(nil), r.services...)
	r.mu.Unlock()
	for _, svc := range services {
		go func(service *serviceProcess) {
			err := <-service.done
			if err != nil {
				r.cfg.logger.Log(service.name, "process exited: "+err.Error())
			} else {
				r.cfg.logger.Log(service.name, "process exited")
			}
			done <- service.name
		}(svc)
	}
	for {
		select {
		case <-ctx.Done():
			return nil
		case name := <-done:
			if name == "electron" || name == "backend" || name == "renderer" {
				r.cfg.logger.Log("launcher", name+" stopped; shutting down supervised session")
				r.StopAll()
				return nil
			}
		}
	}
}

func (r *commandRunner) startService(ctx context.Context, name, workdir, exe string, args ...string) error {
	cmd := exec.CommandContext(ctx, exe, args...)
	cmd.Dir = workdir
	cmd.Env = r.cfg.envList()
	cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: 0x00000200}

	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return err
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		return err
	}
	if err := cmd.Start(); err != nil {
		return err
	}
	svc := &serviceProcess{name: name, cmd: cmd, done: make(chan error, 1)}
	r.mu.Lock()
	r.services = append(r.services, svc)
	r.mu.Unlock()
	r.cfg.logger.Log(name, fmt.Sprintf("started pid=%d", cmd.Process.Pid))
	go r.stream(name, stdout)
	go r.stream(name, stderr)
	go func() {
		svc.done <- cmd.Wait()
	}()
	return nil
}

func (r *commandRunner) runLogged(ctx context.Context, name, workdir, exe string, args ...string) error {
	cmd := exec.CommandContext(ctx, exe, args...)
	cmd.Dir = workdir
	cmd.Env = r.cfg.envList()
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return err
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		return err
	}
	if err := cmd.Start(); err != nil {
		return err
	}
	go r.stream(name, stdout)
	go r.stream(name, stderr)
	if err := cmd.Wait(); err != nil {
		return fmt.Errorf("%s failed: %w", name, err)
	}
	return nil
}

func (r *commandRunner) runCapture(ctx context.Context, name, workdir, exe string, args ...string) (string, error) {
	cmd := exec.CommandContext(ctx, exe, args...)
	cmd.Dir = workdir
	cmd.Env = r.cfg.envList()
	var output bytes.Buffer
	cmd.Stdout = &output
	cmd.Stderr = &output
	if err := cmd.Run(); err != nil {
		r.cfg.logger.Log(name, strings.TrimSpace(output.String()))
		return output.String(), fmt.Errorf("%s failed: %w", name, err)
	}
	return output.String(), nil
}

func (r *commandRunner) stream(name string, reader io.Reader) {
	scanner := bufio.NewScanner(reader)
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	for scanner.Scan() {
		r.cfg.logger.Log(name, scanner.Text())
	}
	if err := scanner.Err(); err != nil && !isBenignLogStreamClose(err) {
		r.cfg.logger.Log(name, "log stream error: "+err.Error())
	}
}

func (r *commandRunner) StopAll() {
	r.mu.Lock()
	services := append([]*serviceProcess(nil), r.services...)
	r.mu.Unlock()
	for i := len(services) - 1; i >= 0; i-- {
		svc := services[i]
		if svc == nil || svc.cmd == nil || svc.cmd.Process == nil || svc.stopped {
			continue
		}
		svc.stopped = true
		pid := fmt.Sprint(svc.cmd.Process.Pid)
		_ = exec.Command("taskkill", "/T", "/F", "/PID", pid).Run()
	}
}

func (r *commandRunner) waitHTTP(ctx context.Context, name, url string, headers map[string]string, timeout time.Duration) error {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if r.httpOK(ctx, url, headers, 5*time.Second) {
			r.cfg.logger.Log(name, "endpoint is responding: "+url)
			return nil
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(1 * time.Second):
		}
	}
	return fmt.Errorf("%s did not respond within %s: %s", name, timeout, url)
}

func (r *commandRunner) httpOK(ctx context.Context, url string, headers map[string]string, timeout time.Duration) bool {
	reqCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	req, err := http.NewRequestWithContext(reqCtx, http.MethodGet, url, nil)
	if err != nil {
		return false
	}
	for key, value := range headers {
		req.Header.Set(key, value)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	return resp.StatusCode >= 200 && resp.StatusCode < 300
}

func (r *commandRunner) postJSON(ctx context.Context, url string, headers map[string]string, body map[string]any, timeout time.Duration) error {
	payload, err := json.Marshal(body)
	if err != nil {
		return err
	}
	reqCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	req, err := http.NewRequestWithContext(reqCtx, http.MethodPost, url, bytes.NewReader(payload))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	for key, value := range headers {
		req.Header.Set(key, value)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("HTTP %d from %s", resp.StatusCode, url)
	}
	return nil
}

func (r *commandRunner) authHeaders() map[string]string {
	token := r.cfg.token
	return map[string]string{
		"Authorization":             "Bearer " + token,
		"x-yuizaki-backend-token":   token,
		"x-yuizaki-control-token":   token,
		"x-yuizaki-supervisor-mode": "1",
	}
}

func (cfg *launcherConfig) refreshURLs() {
	cfg.backendURL = fmt.Sprintf("http://%s:%s", cfg.serverHost, cfg.serverPort)
	cfg.controlURL = fmt.Sprintf("http://%s:%s", cfg.serverHost, cfg.controlPort)
	cfg.rendererOrigin = fmt.Sprintf("http://localhost:%s", cfg.rendererPort)
	if cfg.devRenderer {
		cfg.rendererURL = cfg.rendererOrigin + "/"
		cfg.env["VITE_DEV_SERVER_URL"] = cfg.rendererOrigin
		cfg.env["YUIZAKI_USE_VITE"] = "1"
	} else {
		cfg.rendererURL = cfg.controlURL + "/"
		cfg.env["VITE_DEV_SERVER_URL"] = ""
		cfg.env["YUIZAKI_USE_VITE"] = "0"
	}
	cfg.panelOpenURL = cfg.rendererURL
	if cfg.token != "" {
		cfg.panelOpenURL = cfg.rendererURL + "?control_token=" + cfg.token
	}
	cfg.mcpURL = fmt.Sprintf("http://%s:%s", cfg.serverHost, cfg.mcpPort)
	cfg.env["SERVER_PORT"] = cfg.serverPort
	cfg.env["CONTROL_SERVER_PORT"] = cfg.controlPort
	cfg.env["RENDERER_PORT"] = cfg.rendererPort
	cfg.env["MCP_PORT"] = cfg.mcpPort
	cfg.env["BACKEND_URL"] = cfg.backendURL
	cfg.env["DESKTOP_PET_BACKEND_URL"] = cfg.backendURL
	cfg.env["VITE_YUIZAKI_API_ORIGIN"] = cfg.backendURL
	cfg.env["VITE_YUIZAKI_CONTROL_ORIGIN"] = cfg.controlURL
	cfg.env["RENDERER_ORIGIN"] = cfg.rendererOrigin
	cfg.env["PANEL_URL"] = cfg.controlURL + "/"
	if _, ok := cfg.env["YUIZAKI_ALLOWED_ORIGINS"]; !ok {
		cfg.env["YUIZAKI_ALLOWED_ORIGINS"] = fmt.Sprintf("http://127.0.0.1:%s,http://localhost:%s,http://127.0.0.1:%s,http://localhost:%s", cfg.controlPort, cfg.controlPort, cfg.rendererPort, cfg.rendererPort)
	}
}

func (cfg *launcherConfig) envList() []string {
	keys := make([]string, 0, len(cfg.env))
	for key := range cfg.env {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	result := make([]string, 0, len(keys))
	for _, key := range keys {
		result = append(result, key+"="+cfg.env[key])
	}
	return result
}

func newLogHub(logDir string) (*logHub, error) {
	mainFile, err := os.OpenFile(filepath.Join(logDir, "supervisor.log"), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		return nil, err
	}
	return &logHub{file: mainFile, files: map[string]*os.File{}}, nil
}

func (l *logHub) Log(source, message string) {
	l.mu.Lock()
	defer l.mu.Unlock()
	timestamp := time.Now().Format("15:04:05")
	line := fmt.Sprintf("[%s] [%s] %s", timestamp, source, message)
	fmt.Println(line)
	_, _ = l.file.WriteString(line + "\n")
	if _, ok := l.files[source]; !ok {
		file, err := os.OpenFile(filepath.Join(filepath.Dir(l.file.Name()), source+".supervisor.log"), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
		if err == nil {
			l.files[source] = file
		}
	}
	if file := l.files[source]; file != nil {
		_, _ = file.WriteString(line + "\n")
	}
}

func (l *logHub) Close() {
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.file != nil {
		_ = l.file.Close()
	}
	for _, file := range l.files {
		_ = file.Close()
	}
}

func generateToken() (string, error) {
	buf := make([]byte, 32)
	if _, err := rand.Read(buf); err != nil {
		return "", err
	}
	return strings.TrimRight(base64.URLEncoding.EncodeToString(buf), "="), nil
}

func envMap() map[string]string {
	result := map[string]string{}
	for _, item := range os.Environ() {
		parts := strings.SplitN(item, "=", 2)
		if len(parts) == 2 {
			result[parts[0]] = parts[1]
		}
	}
	return result
}

func envOr(key, fallback string) string {
	value := strings.TrimSpace(os.Getenv(key))
	if value == "" {
		return fallback
	}
	return value
}

func envOrMap(values map[string]string, key, fallback string) string {
	value := strings.TrimSpace(values[key])
	if value == "" {
		return fallback
	}
	return value
}

func firstNonEmptyLine(value string) string {
	for _, line := range strings.Split(value, "\n") {
		line = strings.TrimSpace(line)
		if line != "" {
			return line
		}
	}
	return ""
}

func isBenignLogStreamClose(err error) bool {
	if err == nil {
		return true
	}
	message := strings.ToLower(err.Error())
	benignFragments := []string{
		"file already closed",
		"the pipe has been ended",
		"broken pipe",
		"read |0",
	}
	for _, fragment := range benignFragments {
		if strings.Contains(message, fragment) {
			return true
		}
	}
	return false
}

func init() {
	if os.PathSeparator != '\\' {
		panic(errors.New("YuizakiLauncher is intended for Windows"))
	}
}
