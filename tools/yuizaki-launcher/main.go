package main

import (
	"bufio"
	"bytes"
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"runtime"
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
	defaultMCPEnabled   = true
)

type launcherConfig struct {
	rootDir          string
	pythonDir        string
	electronDir      string
	nodeMCPDir       string
	scriptsDir       string
	logDir           string
	stateDir         string
	statePath        string
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
	autoInstall      bool
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

type electronBuildState struct {
	InputFingerprint  string `json:"inputFingerprint"`
	OutputFingerprint string `json:"outputFingerprint"`
}

type supervisorState struct {
	PID        int            `json:"pid"`
	RootDir    string         `json:"rootDir"`
	StartedAt  string         `json:"startedAt"`
	BackendURL string         `json:"backendUrl"`
	ControlURL string         `json:"controlUrl"`
	MCPURL     string         `json:"mcpUrl"`
	Services   map[string]int `json:"services"`
}

type launcherAction string

const (
	actionStart          launcherAction = "start"
	actionSetup          launcherAction = "setup"
	actionStop           launcherAction = "stop"
	actionStatus         launcherAction = "status"
	actionLogs           launcherAction = "logs"
	actionInstallDesktop launcherAction = "install-desktop"
	actionRemoveDesktop  launcherAction = "remove-desktop"
)

func parseAction(args []string) (launcherAction, []string) {
	if len(args) == 0 {
		return actionStart, args
	}
	switch launcherAction(args[0]) {
	case actionStart, actionSetup, actionStop, actionStatus, actionLogs, actionInstallDesktop, actionRemoveDesktop:
		return launcherAction(args[0]), args[1:]
	default:
		return actionStart, args
	}
}

func resolveProjectRoot() (string, error) {
	exePath, err := os.Executable()
	if err != nil {
		return "", err
	}
	candidates := []string{filepath.Dir(exePath)}
	if cwd, cwdErr := os.Getwd(); cwdErr == nil {
		candidates = append(candidates, cwd)
	}
	for _, candidate := range candidates {
		current, absErr := filepath.Abs(candidate)
		if absErr != nil {
			continue
		}
		for {
			if _, statErr := os.Stat(filepath.Join(current, "electron", "package.json")); statErr == nil {
				return current, nil
			}
			parent := filepath.Dir(current)
			if parent == current {
				break
			}
			current = parent
		}
	}
	return "", fmt.Errorf("Yuizaki project root not found beside launcher or current directory")
}

func launcherStateDir(root string) string {
	if runtime.GOOS == "windows" {
		if base := strings.TrimSpace(os.Getenv("APPDATA")); base != "" {
			return filepath.Join(base, "Yuizaki")
		}
		return filepath.Join(root, ".yuizaki", "state")
	}
	if base := strings.TrimSpace(os.Getenv("XDG_STATE_HOME")); base != "" {
		return filepath.Join(base, "yuizaki")
	}
	if home, err := os.UserHomeDir(); err == nil {
		return filepath.Join(home, ".local", "state", "yuizaki")
	}
	return filepath.Join(root, ".yuizaki", "state")
}

func loadDotEnv(path string, values map[string]string) {
	file, err := os.Open(path)
	if err != nil {
		return
	}
	defer file.Close()
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		line = strings.TrimPrefix(line, "export ")
		parts := strings.SplitN(line, "=", 2)
		if len(parts) != 2 {
			continue
		}
		key := strings.TrimSpace(parts[0])
		if key == "" {
			continue
		}
		value := strings.Trim(strings.TrimSpace(parts[1]), "\"'")
		if strings.TrimSpace(values[key]) == "" {
			values[key] = value
		}
	}
}

func main() {
	action, remaining := parseAction(os.Args[1:])
	if action != actionStart {
		var err error
		switch action {
		case actionSetup:
			err = runSetup(remaining)
		case actionStop:
			err = runStop()
		case actionStatus:
			err = runStatus()
		case actionLogs:
			err = runLogs(remaining)
		case actionInstallDesktop:
			err = runDesktopShortcut(true)
		case actionRemoveDesktop:
			err = runDesktopShortcut(false)
		default:
			err = fmt.Errorf("unknown launcher command: %s", action)
		}
		if err != nil {
			fmt.Fprintf(os.Stderr, "[launcher] %v\n", err)
			os.Exit(1)
		}
		return
	}
	os.Args = append([]string{os.Args[0]}, remaining...)
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
	rootDir, err := resolveProjectRoot()
	if err != nil {
		return nil, err
	}
	rootDir, err = filepath.Abs(rootDir)
	if err != nil {
		return nil, err
	}

	env := envMap()
	loadDotEnv(filepath.Join(rootDir, "python", ".env"), env)
	stateDir := launcherStateDir(rootDir)
	cfg := &launcherConfig{
		rootDir:          rootDir,
		pythonDir:        filepath.Join(rootDir, "python"),
		electronDir:      filepath.Join(rootDir, "electron"),
		nodeMCPDir:       filepath.Join(rootDir, "node-mcp"),
		scriptsDir:       filepath.Join(rootDir, "scripts"),
		logDir:           filepath.Join(rootDir, "logs", "dev"),
		stateDir:         stateDir,
		statePath:        filepath.Join(stateDir, "supervisor.json"),
		withMCP:          mcpEnabled(env),
		devRenderer:      envOrMap(env, "YUIZAKI_USE_VITE", "0") == "1",
		noQdrant:         !qdrantAutoStartEnabled(env),
		serverHost:       envOrMap(env, "SERVER_HOST", "127.0.0.1"),
		serverPort:       envOrMap(env, "SERVER_PORT", defaultBackendPort),
		serverFallbacks:  envOrMap(env, "SERVER_PORT_FALLBACKS", "8011,8012,8013,8014,8015,8021,8022"),
		controlPort:      envOrMap(env, "CONTROL_SERVER_PORT", defaultControlPort),
		controlFallbacks: envOrMap(env, "CONTROL_SERVER_PORT_FALLBACKS", "38946,38947,38948,38949"),
		rendererPort:     envOrMap(env, "RENDERER_PORT", defaultRendererPort),
		renderFallbacks:  envOrMap(env, "RENDERER_PORT_FALLBACKS", "5174,5175,5176,5177"),
		mcpPort:          envOrMap(env, "MCP_PORT", defaultMCPPort),
		autoInstall:      true,
		env:              env,
	}

	flagSet := flag.NewFlagSet(filepath.Base(os.Args[0]), flag.ExitOnError)
	flagSet.BoolVar(&cfg.withMCP, "with-mcp", cfg.withMCP, "start MCP service")
	flagSet.BoolVar(&cfg.noOpen, "no-open", false, "do not open the panel URL")
	flagSet.BoolVar(&cfg.noShowPet, "no-show-pet", false, "do not restore the desktop pet layer")
	flagSet.BoolVar(&cfg.noQdrant, "no-qdrant", cfg.noQdrant, "skip Qdrant Docker auto-start")
	withQdrant := flagSet.Bool("with-qdrant", false, "start Qdrant Docker when memory backend needs it")
	flagSet.BoolVar(&cfg.smoke, "smoke", false, "run lightweight smoke checks after startup")
	flagSet.BoolVar(&cfg.checkOnly, "check", false, "run startup preflight checks only")
	noInstall := flagSet.Bool("no-install", false, "disable automatic dependency installation")
	noMCP := flagSet.Bool("no-mcp", false, "do not start MCP service")
	noDevRenderer := flagSet.Bool("no-dev-renderer", false, "serve built renderer through Electron control server")
	devRenderer := flagSet.Bool("dev-renderer", cfg.devRenderer, "start Vite dev renderer")
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
	if *withQdrant {
		cfg.noQdrant = false
	}
	if *noInstall {
		cfg.autoInstall = false
	}

	if err := os.MkdirAll(cfg.logDir, 0o755); err != nil {
		return nil, err
	}
	logger, err := newLogHub(cfg.logDir)
	if err != nil {
		return nil, err
	}
	cfg.logger = logger

	cfg.token = cfg.env["YUIZAKI_BACKEND_API_TOKEN"]
	if cfg.token == "" {
		token, err := generateToken()
		if err != nil {
			return nil, err
		}
		cfg.token = token
	}
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

	if err := r.ensureFirstRun(ctx); err != nil {
		return err
	}
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
		if cfg.smoke {
			if err := r.waitPetReady(ctx, 30*time.Second); err != nil {
				return err
			}
		}
	}
	if !cfg.noOpen {
		r.openPanel()
	}
	r.persistState()

	cfg.logger.Log("launcher", "============================================")
	cfg.logger.Log("launcher", "Yuizaki supervised launch completed")
	cfg.logger.Log("launcher", "Backend  : "+cfg.backendURL)
	cfg.logger.Log("launcher", "Renderer : "+cfg.rendererURL)
	cfg.logger.Log("launcher", "Control  : "+cfg.controlURL+"/")
	cfg.logger.Log("launcher", "Logs     : "+cfg.logDir)
	cfg.logger.Log("launcher", "Press Ctrl+C to stop supervised services.")

	return r.monitor(ctx)
}

func (r *commandRunner) ensureFirstRun(ctx context.Context) error {
	envPath := filepath.Join(r.cfg.pythonDir, ".env")
	if _, err := os.Stat(envPath); os.IsNotExist(err) && !r.cfg.checkOnly {
		templatePath := filepath.Join(r.cfg.pythonDir, ".env.example")
		if err := copyFile(templatePath, envPath); err != nil {
			return fmt.Errorf("create first-run configuration: %w", err)
		}
		r.cfg.logger.Log("setup", "Created python/.env from .env.example")
		if isInteractiveTerminal() {
			if err := runSetupWizardForRoot(r.cfg.rootDir); err != nil {
				return err
			}
		}
	}
	loadDotEnv(envPath, r.cfg.env)
	if r.cfg.autoInstall && !r.cfg.checkOnly && !runtimeDependenciesReady(r.cfg) {
		profile := "core"
		if strings.EqualFold(strings.TrimSpace(r.cfg.env["YUIZAKI_INSTALL_PROFILE"]), "full") {
			profile = "full"
		}
		r.cfg.logger.Log("setup", "Runtime dependencies are incomplete; installing profile "+profile)
		return r.installRuntime(ctx, profile)
	}
	return nil
}

func (r *commandRunner) installRuntime(ctx context.Context, profile string) error {
	if profile != "core" && profile != "full" {
		return fmt.Errorf("unsupported install profile %q", profile)
	}
	if _, err := exec.LookPath(nodeExecutable()); err != nil {
		return fmt.Errorf("Node.js is required: %w", err)
	}
	npm := "npm"
	if runtime.GOOS == "windows" {
		npm = "npm.cmd"
	}
	if _, err := exec.LookPath(npm); err != nil {
		return fmt.Errorf("npm is required: %w", err)
	}
	if err := r.runLogged(ctx, "install-electron", r.cfg.electronDir, npm, "ci"); err != nil {
		return err
	}
	if err := r.runLogged(ctx, "install-electron-runtime", r.cfg.electronDir, npm, "run", "install:runtime"); err != nil {
		return err
	}
	if err := r.runLogged(ctx, "install-mcp", r.cfg.nodeMCPDir, npm, "ci"); err != nil {
		return err
	}

	pythonCommand, pythonArgs := pythonBootstrapCommand()
	if _, err := exec.LookPath(pythonCommand); err != nil {
		return fmt.Errorf("Python is required: %w", err)
	}
	venvPath := filepath.Join(r.cfg.pythonDir, ".venv")
	pythonExe := pythonExecutable(r.cfg.pythonDir)
	if _, err := os.Stat(pythonExe); os.IsNotExist(err) {
		args := append(append([]string{}, pythonArgs...), "-m", "venv", venvPath)
		if err := r.runLogged(ctx, "install-python-venv", r.cfg.pythonDir, pythonCommand, args...); err != nil {
			return err
		}
	}
	lockName := "requirements-core-lock-linux.txt"
	if runtime.GOOS == "windows" {
		lockName = "requirements-core-lock-windows.txt"
	}
	if profile == "full" {
		lockName = strings.Replace(lockName, "core-", "", 1)
	}
	lockPath := filepath.Join(r.cfg.pythonDir, lockName)
	if err := r.runLogged(ctx, "install-python", r.cfg.pythonDir, pythonExe, "-m", "pip", "install", "--upgrade", "pip"); err != nil {
		return err
	}
	if err := r.runLogged(ctx, "install-python-lock", r.cfg.pythonDir, pythonExe, "-m", "pip", "install", "-r", lockPath); err != nil {
		return err
	}
	if err := r.runLogged(ctx, "install-python-check", r.cfg.pythonDir, pythonExe, "-m", "pip", "check"); err != nil {
		return err
	}
	if err := r.runLogged(ctx, "install-python-lock-check", r.cfg.pythonDir, pythonExe, "scripts/check_installed_lock.py", "--lock", lockName); err != nil {
		return err
	}
	envPath := filepath.Join(r.cfg.pythonDir, ".env")
	if _, err := os.Stat(envPath); os.IsNotExist(err) {
		if err := copyFile(filepath.Join(r.cfg.pythonDir, ".env.example"), envPath); err != nil {
			return err
		}
		r.cfg.logger.Log("setup", "Created python/.env from .env.example")
	}
	return nil
}

func pythonBootstrapCommand() (string, []string) {
	if runtime.GOOS == "windows" {
		if _, err := exec.LookPath("py"); err == nil {
			return "py", []string{"-3"}
		}
		return "python", nil
	}
	if _, err := exec.LookPath("python3"); err == nil {
		return "python3", nil
	}
	return "python", nil
}

func runtimeDependenciesReady(cfg *launcherConfig) bool {
	electronPackage := filepath.Join(cfg.electronDir, "node_modules", "electron", "package.json")
	mcpPackage := filepath.Join(cfg.nodeMCPDir, "node_modules")
	pythonExecutable := filepath.Join(cfg.pythonDir, ".venv", "Scripts", "python.exe")
	if runtime.GOOS != "windows" {
		pythonExecutable = filepath.Join(cfg.pythonDir, ".venv", "bin", "python")
	}
	if _, err := os.Stat(electronPackage); err != nil {
		return false
	}
	if cfg.withMCP {
		if _, err := os.Stat(mcpPackage); err != nil {
			return false
		}
	}
	_, err := os.Stat(pythonExecutable)
	return err == nil
}

func isInteractiveTerminal() bool {
	info, err := os.Stdin.Stat()
	return err == nil && info.Mode()&os.ModeCharDevice != 0
}

func copyFile(source, target string) error {
	data, err := os.ReadFile(source)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
		return err
	}
	return os.WriteFile(target, data, 0o600)
}

func (r *commandRunner) preflight(ctx context.Context) error {
	for _, command := range []string{nodeExecutable(), "npm"} {
		if _, err := exec.LookPath(command); err != nil {
			return fmt.Errorf("required command %q is not available: %w", command, err)
		}
	}
	for _, path := range []string{
		filepath.Join(r.cfg.pythonDir, "app.py"),
		filepath.Join(r.cfg.pythonDir, ".env.example"),
		filepath.Join(r.cfg.electronDir, "package.json"),
		filepath.Join(r.cfg.electronDir, "src", "main", "index.ts"),
		filepath.Join(r.cfg.nodeMCPDir, "server.mjs"),
	} {
		if _, err := os.Stat(path); err != nil {
			return fmt.Errorf("required project file is missing: %s", path)
		}
	}
	if !runtimeDependenciesReady(r.cfg) {
		return fmt.Errorf("runtime dependencies are incomplete; rerun without --check to install them")
	}
	r.cfg.logger.Log("preflight", "runtime and project checks passed")
	return nil
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
	ports := append([]string{preferred}, strings.Split(fallbacks, ",")...)
	seen := map[string]bool{}
	for _, port := range ports {
		port = strings.TrimSpace(port)
		if port == "" || seen[port] {
			continue
		}
		seen[port] = true
		healthPath := "/api/ping"
		switch mode {
		case "control":
			healthPath = "/api/health"
		case "mcp":
			healthPath = "/health"
		case "renderer":
			healthPath = "/"
		}
		if r.httpOK(ctx, fmt.Sprintf("http://%s:%s%s", r.cfg.serverHost, port, healthPath), nil, 2*time.Second) {
			return port, "healthy", nil
		}
		listener, err := net.Listen("tcp", net.JoinHostPort(r.cfg.serverHost, port))
		if err == nil {
			_ = listener.Close()
			return port, "available", nil
		}
	}
	return "", "blocked", fmt.Errorf("all %s ports are occupied", mode)
}

func (r *commandRunner) buildElectron(ctx context.Context) error {
	outputPath := filepath.Join(r.cfg.electronDir, "dist", "main", "index.js")
	outputs := []string{filepath.Join(r.cfg.electronDir, "dist", "main"), filepath.Join(r.cfg.electronDir, "dist", "preload"), filepath.Join(r.cfg.electronDir, "dist", "shared")}
	if !r.cfg.devRenderer {
		outputs = append(outputs, filepath.Join(r.cfg.electronDir, "dist", "renderer"))
	}
	statePath := filepath.Join(r.cfg.electronDir, "dist", ".launcher-build.json")
	inputs := []string{
		filepath.Join(r.cfg.electronDir, "src"),
		filepath.Join(r.cfg.electronDir, "package.json"),
		filepath.Join(r.cfg.electronDir, "package-lock.json"),
		filepath.Join(r.cfg.electronDir, "tsconfig.json"),
		filepath.Join(r.cfg.electronDir, "vite.config.ts"),
	}
	if buildIsCurrent(outputPath, statePath, inputs, outputs) {
		r.cfg.logger.Log("build", "Electron build is current; skipping frontend and TypeScript compilation")
		return nil
	}

	script := "build:electron"
	if !r.cfg.devRenderer {
		script = "build"
	}
	if err := r.runNpm(ctx, "build", script); err != nil {
		return err
	}
	inputFingerprint, inputErr := buildFingerprint(inputs)
	outputFingerprint, outputErr := buildFingerprint(outputs)
	if inputErr == nil && outputErr == nil {
		if err := writeBuildState(statePath, inputFingerprint, outputFingerprint); err != nil {
			r.cfg.logger.Log("build", "build-state warning: "+err.Error())
		}
	} else {
		r.cfg.logger.Log("build", "build-state warning: unable to fingerprint build inputs or outputs")
	}
	return nil
}

func buildIsCurrent(outputPath, statePath string, inputs, outputs []string) bool {
	if buildRequired(outputPath, inputs) {
		return false
	}
	inputFingerprint, inputErr := buildFingerprint(inputs)
	outputFingerprint, outputErr := buildFingerprint(outputs)
	return inputErr == nil && outputErr == nil && buildStateMatches(statePath, inputFingerprint, outputFingerprint)
}

func buildRequired(outputPath string, inputs []string) bool {
	outputInfo, err := os.Stat(outputPath)
	if err != nil {
		return true
	}
	for _, input := range inputs {
		err := filepath.WalkDir(input, func(_ string, entry os.DirEntry, walkErr error) error {
			if walkErr != nil {
				return walkErr
			}
			if entry.IsDir() {
				return nil
			}
			info, infoErr := entry.Info()
			if infoErr != nil {
				return infoErr
			}
			if !info.ModTime().Before(outputInfo.ModTime()) {
				return errors.New("build input is newer than output")
			}
			return nil
		})
		if err != nil {
			return true
		}
	}
	return false
}

func buildFingerprint(inputs []string) (string, error) {
	files := make([]string, 0)
	for _, input := range inputs {
		err := filepath.WalkDir(input, func(path string, entry os.DirEntry, walkErr error) error {
			if walkErr != nil {
				return walkErr
			}
			if !entry.IsDir() {
				files = append(files, path)
			}
			return nil
		})
		if err != nil {
			return "", err
		}
	}
	sort.Strings(files)
	hash := sha256.New()
	for _, path := range files {
		content, err := os.ReadFile(path)
		if err != nil {
			return "", err
		}
		_, _ = io.WriteString(hash, filepath.ToSlash(path))
		_, _ = hash.Write([]byte{0})
		_, _ = hash.Write(content)
		_, _ = hash.Write([]byte{0})
	}
	return hex.EncodeToString(hash.Sum(nil)), nil
}

func buildStateMatches(statePath, inputFingerprint, outputFingerprint string) bool {
	content, err := os.ReadFile(statePath)
	if err != nil {
		return false
	}
	var state electronBuildState
	return json.Unmarshal(content, &state) == nil &&
		state.InputFingerprint == inputFingerprint &&
		state.OutputFingerprint == outputFingerprint
}

func writeBuildState(statePath, inputFingerprint, outputFingerprint string) error {
	content, err := json.Marshal(electronBuildState{
		InputFingerprint:  inputFingerprint,
		OutputFingerprint: outputFingerprint,
	})
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(statePath), 0o755); err != nil {
		return err
	}
	temporaryPath := statePath + ".tmp"
	if err := os.WriteFile(temporaryPath, append(content, '\n'), 0o644); err != nil {
		return err
	}
	if err := os.Remove(statePath); err != nil && !os.IsNotExist(err) {
		return err
	}
	return os.Rename(temporaryPath, statePath)
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
	if runtime.GOOS != "windows" {
		r.cfg.logger.Log("qdrant", "Qdrant auto-start is not managed by the Linux launcher; start the configured Docker service separately")
		return nil
	}
	return r.runLogged(ctx, "qdrant", r.cfg.rootDir, "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", filepath.Join(r.cfg.scriptsDir, "ensure_qdrant_docker.ps1"), "-ProjectRoot", r.cfg.rootDir, "-SettingsPath", filepath.Join(r.cfg.pythonDir, "config", "settings.json"), "-EnvPath", filepath.Join(r.cfg.pythonDir, ".env"))
}

func (r *commandRunner) checkDatabaseMigrations(ctx context.Context) {
	pythonExe := pythonExecutable(r.cfg.pythonDir)
	err := r.runLogged(ctx, "migration-check", r.cfg.pythonDir, pythonExe, "migration_check.py")
	if err != nil {
		r.cfg.logger.Log("migration-check", "schema is not at Alembic head; backend runner will auto-migrate on startup")
	}
}

func (r *commandRunner) startBackend(ctx context.Context) error {
	if err := r.runLogged(ctx, "migration-bootstrap", r.cfg.pythonDir, pythonExecutable(r.cfg.pythonDir), "migration_bootstrap.py"); err != nil {
		return err
	}
	return r.startService(ctx, "backend", r.cfg.pythonDir, pythonExecutable(r.cfg.pythonDir), "-m", "uvicorn", "app:app", "--host", r.cfg.serverHost, "--port", r.cfg.serverPort, "--env-file", filepath.Join(r.cfg.pythonDir, ".env"), "--log-level", "info")
}

func (r *commandRunner) ensureMCP(ctx context.Context) error {
	if r.httpOK(ctx, r.cfg.mcpURL+"/health", nil, 3*time.Second) {
		r.cfg.logger.Log("mcp", "Reusing existing MCP service: "+r.cfg.mcpURL)
		return nil
	}
	if err := r.startService(ctx, "mcp", r.cfg.nodeMCPDir, nodeExecutable(), "server.mjs"); err != nil {
		return err
	}
	return r.waitHTTP(ctx, "mcp", r.cfg.mcpURL+"/health", nil, 120*time.Second)
}

func (r *commandRunner) ensureRenderer(ctx context.Context) error {
	if r.httpOK(ctx, r.cfg.rendererURL, nil, 2*time.Second) {
		r.cfg.logger.Log("renderer", "Reusing existing renderer: "+r.cfg.rendererURL)
		return nil
	}
	if err := r.startService(ctx, "renderer", r.cfg.electronDir, nodeExecutable(), filepath.Join(r.cfg.electronDir, "node_modules", "vite", "bin", "vite.js"), "--host", "127.0.0.1", "--port", r.cfg.rendererPort); err != nil {
		return err
	}
	return r.waitHTTP(ctx, "renderer", r.cfg.rendererURL, nil, 120*time.Second)
}

func (r *commandRunner) startElectron(ctx context.Context) error {
	return r.startService(ctx, "electron", r.cfg.electronDir, nodeExecutable(), filepath.Join(r.cfg.electronDir, "scripts", "run-electron.mjs"))
}

func pythonExecutable(pythonDir string) string {
	if runtime.GOOS == "windows" {
		return filepath.Join(pythonDir, ".venv", "Scripts", "python.exe")
	}
	return filepath.Join(pythonDir, ".venv", "bin", "python")
}

func nodeExecutable() string {
	if runtime.GOOS == "windows" {
		return "node.exe"
	}
	return "node"
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

func (r *commandRunner) waitPetReady(ctx context.Context, timeout time.Duration) error {
	url := r.cfg.controlURL + "/api/pet/state"
	headers := r.authHeaders()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if r.petReady(ctx, url, headers, 5*time.Second) {
			r.cfg.logger.Log("smoke", "desktop pet renderer is ready")
			return nil
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(1 * time.Second):
		}
	}
	return fmt.Errorf("desktop pet renderer did not become ready within %s", timeout)
}

func (r *commandRunner) petReady(ctx context.Context, url string, headers map[string]string, timeout time.Duration) bool {
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
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return false
	}
	var state struct {
		Ready bool `json:"ready"`
	}
	return json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(&state) == nil && state.Ready
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
	if err := openURL(r.cfg.panelOpenURL); err != nil {
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
	configureChildProcess(cmd)

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
	r.persistState()
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
	configureChildProcess(cmd)
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

func (r *commandRunner) runNpm(ctx context.Context, name, script string) error {
	executable := "npm"
	if runtime.GOOS == "windows" {
		executable = "npm.cmd"
	}
	return r.runLogged(ctx, name, r.cfg.electronDir, executable, "run", script)
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
		_ = stopChildProcess(svc.cmd)
	}
	_ = os.Remove(r.cfg.statePath)
}

func (r *commandRunner) persistState() {
	state := supervisorState{
		PID:        os.Getpid(),
		RootDir:    r.cfg.rootDir,
		StartedAt:  time.Now().UTC().Format(time.RFC3339),
		BackendURL: r.cfg.backendURL,
		ControlURL: r.cfg.controlURL,
		MCPURL:     r.cfg.mcpURL,
		Services:   map[string]int{},
	}
	r.mu.Lock()
	for _, service := range r.services {
		if service != nil && service.cmd != nil && service.cmd.Process != nil && !service.stopped {
			state.Services[service.name] = service.cmd.Process.Pid
		}
	}
	r.mu.Unlock()
	if len(state.Services) == 0 {
		return
	}
	if err := os.MkdirAll(r.cfg.stateDir, 0o755); err != nil {
		r.cfg.logger.Log("launcher", "state write failed: "+err.Error())
		return
	}
	data, err := json.MarshalIndent(state, "", "  ")
	if err != nil {
		return
	}
	tmp := r.cfg.statePath + ".tmp"
	if err := os.WriteFile(tmp, append(data, '\n'), 0o600); err != nil {
		return
	}
	if err := os.Rename(tmp, r.cfg.statePath); err != nil {
		_ = os.Remove(tmp)
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

func qdrantAutoStartEnabled(values map[string]string) bool {
	if setting := strings.TrimSpace(values["QDRANT_AUTO_START"]); setting != "" {
		return setting == "1" || strings.EqualFold(setting, "true")
	}
	return strings.EqualFold(strings.TrimSpace(values["MEMORY_BACKEND"]), "qdrant")
}

func mcpEnabled(values map[string]string) bool {
	if setting := strings.TrimSpace(values["YUIZAKI_WITH_MCP"]); setting != "" {
		return setting == "1" || strings.EqualFold(setting, "true")
	}
	return defaultMCPEnabled
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

func runSetup(_ []string) error {
	root, err := resolveProjectRoot()
	if err != nil {
		return err
	}
	return runSetupWizardForRoot(root)
}

func runSetupWizardForRoot(root string) error {
	envPath := filepath.Join(root, "python", ".env")
	if _, err := os.Stat(envPath); os.IsNotExist(err) {
		if err := copyFile(filepath.Join(root, "python", ".env.example"), envPath); err != nil {
			return err
		}
	}
	values := map[string]string{}
	loadDotEnv(envPath, values)
	reader := bufio.NewReader(os.Stdin)
	fmt.Println("Yuizaki first-run setup")
	fmt.Println("Leave a value empty to keep the current setting.")
	values["LLM_PROVIDER"] = promptValue(reader, "LLM provider", values["LLM_PROVIDER"], "custom")
	values["LLM_BASE_URL"] = promptValue(reader, "API base URL", values["LLM_BASE_URL"], "")
	values["LLM_API_KEY"] = promptSecretValue(reader, values["LLM_API_KEY"])
	values["LLM_MODEL"] = promptValue(reader, "Chat model", values["LLM_MODEL"], "gpt-4o-mini")
	values["YUIZAKI_INSTALL_PROFILE"] = promptValue(reader, "Install profile (core/full)", values["YUIZAKI_INSTALL_PROFILE"], "core")
	return updateDotEnv(envPath, values)
}

func promptValue(reader *bufio.Reader, label, current, fallback string) string {
	display := current
	if display == "" {
		display = fallback
	}
	fmt.Printf("%s [%s]: ", label, display)
	line, err := reader.ReadString('\n')
	if err != nil && len(line) == 0 {
		return display
	}
	line = strings.TrimSpace(line)
	if line == "" {
		return display
	}
	return line
}

func promptSecretValue(reader *bufio.Reader, current string) string {
	display := ""
	if current != "" {
		display = "configured"
	}
	fmt.Printf("API key [%s]: ", display)
	line, err := reader.ReadString('\n')
	if err != nil && len(line) == 0 {
		return current
	}
	line = strings.TrimSpace(line)
	if line == "" {
		return current
	}
	return line
}

func updateDotEnv(path string, updates map[string]string) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	lines := strings.Split(strings.ReplaceAll(string(data), "\r\n", "\n"), "\n")
	seen := map[string]bool{}
	for index, line := range lines {
		trimmed := strings.TrimSpace(line)
		if trimmed == "" || strings.HasPrefix(trimmed, "#") {
			continue
		}
		parts := strings.SplitN(trimmed, "=", 2)
		if len(parts) != 2 {
			continue
		}
		key := strings.TrimSpace(strings.TrimPrefix(parts[0], "export "))
		value, ok := updates[key]
		if !ok {
			continue
		}
		lines[index] = key + "=" + strings.ReplaceAll(value, "\n", "")
		seen[key] = true
	}
	for key, value := range updates {
		if !seen[key] && value != "" {
			lines = append(lines, key+"="+strings.ReplaceAll(value, "\n", ""))
		}
	}
	return os.WriteFile(path, []byte(strings.Join(lines, "\n")), 0o600)
}

func runStop() error {
	root, err := resolveProjectRoot()
	if err != nil {
		return err
	}
	statePath := filepath.Join(launcherStateDir(root), "supervisor.json")
	state, err := readSupervisorState(statePath)
	if os.IsNotExist(err) {
		fmt.Println("Yuizaki is not running.")
		return nil
	}
	if err != nil {
		return err
	}
	for name, pid := range state.Services {
		if err := stopPID(pid); err != nil {
			fmt.Printf("[WARN] %s pid %d: %v\n", name, pid, err)
		} else {
			fmt.Printf("[OK] stopped %s (pid %d)\n", name, pid)
		}
	}
	return os.Remove(statePath)
}

func runStatus() error {
	root, err := resolveProjectRoot()
	if err != nil {
		return err
	}
	statePath := filepath.Join(launcherStateDir(root), "supervisor.json")
	state, err := readSupervisorState(statePath)
	if os.IsNotExist(err) {
		fmt.Println("status: stopped")
		return nil
	}
	if err != nil {
		return err
	}
	controlOK := httpEndpointOK(state.ControlURL + "/api/health")
	backendOK := httpEndpointOK(state.BackendURL + "/api/ping")
	mcpOK := httpEndpointOK(state.MCPURL + "/health")
	_, mcpRequired := state.Services["mcp"]
	fmt.Printf("status: %s\n", map[bool]string{true: "running", false: "degraded"}[controlOK && backendOK && (!mcpRequired || mcpOK)])
	fmt.Printf("control: %s\nbackend: %s\nmcp: %s\n", state.ControlURL, state.BackendURL, state.MCPURL)
	for name, pid := range state.Services {
		fmt.Printf("service.%s: pid=%d\n", name, pid)
	}
	if !controlOK || !backendOK || (mcpRequired && !mcpOK) {
		return fmt.Errorf("one or more supervised endpoints are unavailable")
	}
	return nil
}

func readSupervisorState(path string) (supervisorState, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return supervisorState{}, err
	}
	var state supervisorState
	if err := json.Unmarshal(data, &state); err != nil {
		return supervisorState{}, err
	}
	return state, nil
}

func httpEndpointOK(url string) bool {
	client := http.Client{Timeout: 2 * time.Second}
	response, err := client.Get(url)
	if err != nil {
		return false
	}
	defer response.Body.Close()
	return response.StatusCode >= 200 && response.StatusCode < 300
}

func runLogs(args []string) error {
	root, err := resolveProjectRoot()
	if err != nil {
		return err
	}
	logPath := filepath.Join(root, "logs", "dev", "supervisor.log")
	data, err := os.ReadFile(logPath)
	if err != nil {
		return err
	}
	lines := strings.Split(strings.TrimRight(string(data), "\r\n"), "\n")
	start := 0
	if len(lines) > 200 {
		start = len(lines) - 200
	}
	follow := len(args) > 0 && (args[0] == "--follow" || args[0] == "-f")
	fmt.Println(strings.Join(lines[start:], "\n"))
	if !follow {
		return nil
	}
	file, err := os.Open(logPath)
	if err != nil {
		return err
	}
	defer file.Close()
	if _, err := file.Seek(0, io.SeekEnd); err != nil {
		return err
	}
	reader := bufio.NewReader(file)
	for {
		line, readErr := reader.ReadString('\n')
		if len(line) > 0 {
			fmt.Print(line)
		}
		if readErr != nil {
			time.Sleep(500 * time.Millisecond)
		}
	}
}

func runDesktopShortcut(install bool) error {
	root, err := resolveProjectRoot()
	if err != nil {
		return err
	}
	executable, err := os.Executable()
	if err != nil {
		return err
	}
	if runtime.GOOS == "windows" {
		return installWindowsShortcut(install, root, executable)
	}
	return installLinuxDesktopEntry(install, root, executable)
}

func openURL(url string) error {
	if runtime.GOOS == "windows" {
		return exec.Command("rundll32.exe", "url.dll,FileProtocolHandler", url).Start()
	}
	return exec.Command("xdg-open", url).Start()
}

func init() {
	// The supervised launcher is intentionally cross-platform. Platform-specific
	// process-group and shortcut behavior lives in build-tagged helpers.
}
