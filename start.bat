@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "WITH_MCP=1"
set "CHECK_ONLY=0"
set "DEV_RENDERER=0"
set "SMOKE=0"
set "VERIFY=0"
set "NO_PAUSE=0"
set "NO_OPEN=0"
set "SHOW_PET=1"
if not defined QDRANT_AUTO_START set "QDRANT_AUTO_START=0"
for %%A in (%*) do (
  if /I "%%~A"=="--with-mcp" set "WITH_MCP=1"
  if /I "%%~A"=="--no-mcp" set "WITH_MCP=0"
  if /I "%%~A"=="--with-qdrant" set "QDRANT_AUTO_START=1"
  if /I "%%~A"=="--check" set "CHECK_ONLY=1"
  if /I "%%~A"=="--dev-renderer" set "DEV_RENDERER=1"
  if /I "%%~A"=="--no-dev-renderer" set "DEV_RENDERER=0"
  if /I "%%~A"=="--smoke" set "SMOKE=1"
  if /I "%%~A"=="--verify" set "VERIFY=1"
  if /I "%%~A"=="--no-pause" set "NO_PAUSE=1"
  if /I "%%~A"=="--no-open" set "NO_OPEN=1"
  if /I "%%~A"=="--no-show-pet" set "SHOW_PET=0"
  if /I "%%~A"=="--no-qdrant" set "QDRANT_AUTO_START=0"
)

set "NO_OPTIONAL_INSTALL=0"
if "%CHECK_ONLY%"=="1" set "NO_OPTIONAL_INSTALL=1"
if "%VERIFY%"=="1" set "NO_OPTIONAL_INSTALL=1"

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

set "APP_ENV=development"
set "ENV=development"
set "NODE_ENV=development"
set "SCHEMA_MIGRATION_MODE=bootstrap"
if not defined SERVER_HOST set "SERVER_HOST=127.0.0.1"
if not defined SERVER_PORT set "SERVER_PORT=8001"
if not defined SERVER_PORT_FALLBACKS set "SERVER_PORT_FALLBACKS=8011,8012,8013,8014,8015,8021,8022"
if not defined CONTROL_SERVER_PORT set "CONTROL_SERVER_PORT=38945"
if not defined CONTROL_SERVER_PORT_FALLBACKS set "CONTROL_SERVER_PORT_FALLBACKS=38946,38947,38948,38949"
set "MCP_PORT=7777"
if not defined RENDERER_PORT set "RENDERER_PORT=5173"
if not defined RENDERER_PORT_FALLBACKS set "RENDERER_PORT_FALLBACKS=5174,5175,5176,5177"
set "RENDERER_ORIGIN=http://localhost:%RENDERER_PORT%"
set "PANEL_URL=http://%SERVER_HOST%:%CONTROL_SERVER_PORT%/"
set "MCP_URL=http://%SERVER_HOST%:%MCP_PORT%"
set "SERVER_DEBUG=true"
set "LOG_LEVEL=DEBUG"
set "MAX_BACKEND_WAIT_SECONDS=120"
set "MAX_CONTROL_WAIT_SECONDS=240"
set "PYTHONUNBUFFERED=1"
set "PYTHONIOENCODING=utf-8"
set "DESKTOP_PET_SKIP_INTERNAL_PYTHON=1"
if defined YUIZAKI_ALLOWED_ORIGINS set "YUIZAKI_ALLOWED_ORIGINS_USER=1"
call :refresh_backend_urls
call :refresh_control_urls
if not defined VITE_YUIZAKI_API_ORIGIN set "VITE_YUIZAKI_API_ORIGIN=%BACKEND_URL%"
set "VITE_DEV_SERVER_URL="
set "YUIZAKI_USE_VITE=%DEV_RENDERER%"
set "RENDERER_URL=%PANEL_URL%"
set "PANEL_OPEN_URL=%RENDERER_URL%"
set "ELECTRON_RUN_AS_NODE="
if not defined YUIZAKI_CONTROL_TOKEN (
  if defined YUIZAKI_BACKEND_API_TOKEN (
    set "YUIZAKI_CONTROL_TOKEN=%YUIZAKI_BACKEND_API_TOKEN%"
  ) else (
    call :generate_control_token
  )
)
call :align_backend_api_token

set "PYTHON_DIR=%SCRIPT_DIR%\python"
set "ELECTRON_DIR=%SCRIPT_DIR%\electron"
set "NODE_MCP_DIR=%SCRIPT_DIR%\node-mcp"
set "PYTHON_EXE=%PYTHON_DIR%\.venv\Scripts\python.exe"
set "PYTHON_ENV_FILE=%PYTHON_DIR%\.env"
set "PYTHON_ENV_TEMPLATE=%PYTHON_DIR%\.env.example"
set "PYTHON_SETTINGS_FILE=%PYTHON_DIR%\config\settings.json"
set "ELECTRON_PACKAGE_JSON=%ELECTRON_DIR%\package.json"
set "ELECTRON_NODE_MODULES=%ELECTRON_DIR%\node_modules"
set "NODE_MCP_NODE_MODULES=%NODE_MCP_DIR%\node_modules"
set "ELECTRON_MAIN_ENTRY=%ELECTRON_DIR%\src\main\index.ts"
set "PYTHON_APP_ENTRY=%PYTHON_DIR%\app.py"
set "RUN_BACKEND_SCRIPT=%SCRIPT_DIR%\scripts\run_backend_dev.bat"
set "RUN_ELECTRON_SCRIPT=%SCRIPT_DIR%\scripts\run_electron_dev.bat"
set "RUN_RENDERER_SCRIPT=%SCRIPT_DIR%\scripts\run_renderer_dev.bat"
set "RUN_ELECTRON_APP_SCRIPT=%SCRIPT_DIR%\scripts\run_electron_app.bat"
set "RUN_MCP_SCRIPT=%SCRIPT_DIR%\scripts\run_mcp_dev.bat"
set "SELECT_STARTUP_PORT_SCRIPT=%SCRIPT_DIR%\scripts\select_startup_port.ps1"
set "ENSURE_QDRANT_DOCKER_SCRIPT=%SCRIPT_DIR%\scripts\ensure_qdrant_docker.ps1"
set "LOG_DIR=%SCRIPT_DIR%\logs\dev"
set "LAST_ERROR="
set "BACKEND_ALREADY_RUNNING=0"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>nul

call :log_info "Yuizaki startup initialized"
call :log_info "Project root: %SCRIPT_DIR%"
call :log_info "Mode: %APP_ENV%"
if "%WITH_MCP%"=="1" (
  call :log_info "MCP startup: enabled (default full startup)"
) else (
  call :log_info "MCP startup: disabled (--no-mcp)"
)
if "%DEV_RENDERER%"=="1" (
  set "VITE_DEV_SERVER_URL=%RENDERER_ORIGIN%"
  set "RENDERER_URL=%RENDERER_ORIGIN%/"
  set "YUIZAKI_USE_VITE=1"
  call :log_info "Renderer mode: Vite dev server (!RENDERER_URL!)"
) else (
  set "YUIZAKI_USE_VITE=0"
  call :log_info "Renderer mode: Electron control server (%PANEL_URL%)"
)
call :build_panel_open_url
if "%CHECK_ONLY%"=="1" call :log_info "Check-only mode: startup commands will not be launched"
if "%VERIFY%"=="1" call :log_info "Verify mode: type checks, builds, and tests will run without launching services"
if "%SMOKE%"=="1" call :log_info "Smoke mode: lightweight endpoint checks will run after startup"

call :banner "Stage 1/7 - Environment check"
call :ensure_runtime_environment
if errorlevel 1 goto :fatal

call :banner "Stage 2/7 - Dependency integrity check"
call :ensure_project_integrity
if errorlevel 1 goto :fatal

call :validate_startup_paths
if errorlevel 1 goto :fatal

if "%CHECK_ONLY%"=="1" (
  call :ok "Startup preflight check passed"
  exit /b 0
)

if "%VERIFY%"=="1" (
  call :banner "Verification suite"
  call :run_verify_suite
  if errorlevel 1 goto :fatal
  call :ok "Verification suite passed"
  exit /b 0
)

call :banner "Stage 2.5/7 - Runtime port selection"
call :select_control_port
if errorlevel 1 goto :fatal
call :build_panel_open_url

call :banner "Stage 3/7 - Frontend build"
call :build_frontend_ui
if errorlevel 1 goto :fatal

call :banner "Stage 4/7 - Model cache check"
call :ensure_embedding_model
if errorlevel 1 goto :fatal

if "%QDRANT_AUTO_START%"=="1" (
  call :banner "Stage 4.5/7 - Qdrant Docker check"
  call :ensure_qdrant_docker
  if errorlevel 1 goto :fatal
) else (
  call :log_info "Qdrant Docker check skipped (SQLite/local memory mode)"
)

call :banner "Stage 5/7 - Backend availability check"
call :select_backend_port
if errorlevel 1 goto :fatal
call :check_backend_port
if errorlevel 1 goto :fatal
if "%BACKEND_ALREADY_RUNNING%"=="1" (
  call :adopt_existing_control_token
  call :check_backend_auth_alignment
  if errorlevel 1 goto :fatal
)

if "%BACKEND_ALREADY_RUNNING%"=="0" (
  call :banner "Stage 5.5/7 - Database migration check"
  call :check_database_migrations
  if errorlevel 1 goto :fatal
)

call :banner "Stage 6/7 - Backend startup"
if "%BACKEND_ALREADY_RUNNING%"=="1" (
  call :log_info "Reusing existing backend on %BACKEND_URL%"
) else (
  call :start_backend
  if errorlevel 1 goto :fatal
  call :wait_for_backend
  if errorlevel 1 goto :fatal
)

if "%WITH_MCP%"=="1" (
  call :start_mcp
  if errorlevel 1 goto :fatal
  call :wait_for_mcp
  if errorlevel 1 goto :fatal
)

call :banner "Stage 7/7 - Electron + renderer startup"
if "%DEV_RENDERER%"=="1" (
  call :start_renderer
  if errorlevel 1 goto :fatal
  call :wait_for_renderer
  if errorlevel 1 goto :fatal
) else (
  call :log_info "Skipping Vite dev server; Electron will serve the built UI from dist\renderer"
)
call :start_electron
if errorlevel 1 goto :fatal
call :wait_for_control_server
if errorlevel 1 goto :fatal
call :adopt_existing_control_token
call :verify_control_backend_link_or_restart_control
if errorlevel 1 goto :fatal
call :build_panel_open_url
if "%SMOKE%"=="1" (
  call :banner "Stage 7.5/7 - Lightweight smoke checks"
  call :smoke_core_endpoints
  if errorlevel 1 goto :fatal
)
if "%SHOW_PET%"=="1" (
  call :ensure_pet_visible
  if errorlevel 1 goto :fatal
) else (
  call :log_info "Pet layer auto-show skipped (--no-show-pet)"
)

if "%NO_OPEN%"=="0" (
  start "yuizaki-panel" "%PANEL_OPEN_URL%" >nul 2>nul
) else (
  call :log_info "Panel auto-open skipped (--no-open)"
)

echo.
call :ok "============================================"
call :ok "  Yuizaki launch sequence completed"
call :ok "============================================"
echo.
call :log_info "Backend  : %BACKEND_URL%"
call :log_info "Renderer : %RENDERER_URL%"
call :log_info "Control  : http://%SERVER_HOST%:%CONTROL_SERVER_PORT%/"
call :log_info "Logs     : %LOG_DIR%"
call :log_info "Shortcut : Press ? for help"
echo.
call :log_info "Closing this window will not stop running programs."
if "%NO_PAUSE%"=="1" exit /b 0
pause
exit /b 0

:banner
echo.
echo ============================================================
echo %~1
echo ============================================================
exit /b 0

:log_info
echo [INFO]  %~1
exit /b 0

:info
echo [INFO]  %~1
exit /b 0

:warn
echo [WARN]  %~1
exit /b 0

:ok
echo [OK]    %~1
exit /b 0

:error_msg
echo [ERROR] %~1
exit /b 0

:fail
set "LAST_ERROR=%~1"
exit /b 0

:generate_control_token
for /f "usebackq delims=" %%T in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$bytes=New-Object byte[] 32; $rng=[Security.Cryptography.RandomNumberGenerator]::Create(); $rng.GetBytes($bytes); $rng.Dispose(); [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+','-').Replace('/','_')" 2^>nul`) do set "YUIZAKI_CONTROL_TOKEN=%%T"
if not defined YUIZAKI_CONTROL_TOKEN set "YUIZAKI_CONTROL_TOKEN=yuizaki-local-%RANDOM%%RANDOM%%RANDOM%"
exit /b 0

:align_backend_api_token
if not defined YUIZAKI_CONTROL_TOKEN exit /b 0
if not defined YUIZAKI_BACKEND_API_TOKEN (
  set "YUIZAKI_BACKEND_API_TOKEN=%YUIZAKI_CONTROL_TOKEN%"
  exit /b 0
)
if not "%YUIZAKI_BACKEND_API_TOKEN%"=="%YUIZAKI_CONTROL_TOKEN%" (
  call :warn "YUIZAKI_BACKEND_API_TOKEN differs from YUIZAKI_CONTROL_TOKEN; using one startup token for renderer, Electron, and backend."
  set "YUIZAKI_BACKEND_API_TOKEN=%YUIZAKI_CONTROL_TOKEN%"
)
exit /b 0

:build_panel_open_url
set "PANEL_OPEN_URL=%RENDERER_URL%"
if defined YUIZAKI_CONTROL_TOKEN (
  set "PANEL_OPEN_URL=%RENDERER_URL%?control_token=%YUIZAKI_CONTROL_TOKEN%"
)
exit /b 0

:refresh_backend_urls
set "DESKTOP_PET_BACKEND_URL=http://%SERVER_HOST%:%SERVER_PORT%"
set "BACKEND_URL=http://%SERVER_HOST%:%SERVER_PORT%"
set "VITE_YUIZAKI_API_ORIGIN=%BACKEND_URL%"
exit /b 0

:refresh_control_urls
set "PANEL_URL=http://%SERVER_HOST%:%CONTROL_SERVER_PORT%/"
set "VITE_YUIZAKI_CONTROL_ORIGIN=http://%SERVER_HOST%:%CONTROL_SERVER_PORT%"
if not defined YUIZAKI_ALLOWED_ORIGINS_USER set "YUIZAKI_ALLOWED_ORIGINS=http://127.0.0.1:%CONTROL_SERVER_PORT%,http://localhost:%CONTROL_SERVER_PORT%,http://127.0.0.1:%RENDERER_PORT%,http://localhost:%RENDERER_PORT%"
exit /b 0

:refresh_renderer_urls
set "RENDERER_ORIGIN=http://localhost:%RENDERER_PORT%"
if "%DEV_RENDERER%"=="1" (
  set "VITE_DEV_SERVER_URL=%RENDERER_ORIGIN%"
  set "RENDERER_URL=%RENDERER_ORIGIN%/"
  set "YUIZAKI_USE_VITE=1"
) else (
  set "RENDERER_URL=%PANEL_URL%"
  set "VITE_DEV_SERVER_URL="
  set "YUIZAKI_USE_VITE=0"
)
exit /b 0

:ensure_runtime_environment
call :log_info "Checking PowerShell..."
where powershell >nul 2>nul
if errorlevel 1 (
  call :fail "PowerShell is not available in PATH."
  exit /b 1
)

call :log_info "Checking Node.js..."
where node >nul 2>nul
if errorlevel 1 (
  call :fail "node is not available in PATH. Install Node.js 22.13+."
  exit /b 1
)
node -e "const [major, minor] = process.versions.node.split('.').map(Number); process.exit(major > 22 || (major === 22 && minor >= 13) ? 0 : 1)" >nul 2>nul
if errorlevel 1 (
  for /f %%V in ('node -p "process.versions.node" 2^>nul') do set "NODE_VERSION=%%V"
  if not defined NODE_VERSION set "NODE_VERSION=unknown"
  call :fail "Node.js 22.13+ is required. Current version: %NODE_VERSION%."
  exit /b 1
)

call :log_info "Checking npm..."
where npm >nul 2>nul
if errorlevel 1 (
  call :fail "npm is not available in PATH. Install Node.js 22.13+ and ensure npm is in PATH."
  exit /b 1
)

call :log_info "Checking Python virtual environment..."
if not exist "%PYTHON_EXE%" (
  call :fail "Python virtual environment not found: %PYTHON_EXE%. Run install.bat core or install.bat full first."
  exit /b 1
)
set "PYTHON_VERSION_FILE=%TEMP%\yuizaki-python-version-%RANDOM%.txt"
"%PYTHON_EXE%" -c "import sys; print(sys.version.split()[0])" > "%PYTHON_VERSION_FILE%" 2>nul
if errorlevel 1 (
  del /q "%PYTHON_VERSION_FILE%" >nul 2>nul
  call :fail "Unable to determine Python version from project virtual environment: %PYTHON_EXE%"
  exit /b 1
)
set /p PYTHON_VERSION=<"%PYTHON_VERSION_FILE%"
del /q "%PYTHON_VERSION_FILE%" >nul 2>nul
if not defined PYTHON_VERSION (
  call :fail "Python version probe returned no value: %PYTHON_EXE%"
  exit /b 1
)
call :log_info "Python interpreter: %PYTHON_EXE% (version %PYTHON_VERSION%)"
"%PYTHON_EXE%" -c "import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 14) else 1)" >nul 2>nul
if errorlevel 1 (
  call :fail "Python 3.11, 3.12, or 3.13 is required in the project virtual environment. Current version: %PYTHON_VERSION%"
  exit /b 1
)

call :log_info "Checking python app entry..."
if not exist "%PYTHON_APP_ENTRY%" (
  call :fail "Backend entry file missing: %PYTHON_APP_ENTRY%"
  exit /b 1
)

call :log_info "Checking electron package.json..."
if not exist "%ELECTRON_PACKAGE_JSON%" (
  call :fail "Electron package.json missing: %ELECTRON_PACKAGE_JSON%"
  exit /b 1
)

call :log_info "Checking electron main entry..."
if not exist "%ELECTRON_MAIN_ENTRY%" (
  call :fail "Electron main entry missing: %ELECTRON_MAIN_ENTRY%"
  exit /b 1
)

call :log_info "Checking python env file..."
if not exist "%PYTHON_ENV_FILE%" (
  if not exist "%PYTHON_ENV_TEMPLATE%" (
    call :fail "Neither %PYTHON_ENV_FILE% nor template %PYTHON_ENV_TEMPLATE% exists."
    exit /b 1
  )
  copy /y "%PYTHON_ENV_TEMPLATE%" "%PYTHON_ENV_FILE%" >nul
  if errorlevel 1 (
    call :fail "Failed to create %PYTHON_ENV_FILE% from template."
    exit /b 1
  )
  call :warn "python\.env was missing. Created from .env.example"
)

call :warn_if_placeholder_llm_key

call :ok "Runtime environment check passed"
exit /b 0

:warn_if_placeholder_llm_key
if not exist "%PYTHON_ENV_FILE%" exit /b 0
call :detect_settings_llm_api_key
if "%SETTINGS_LLM_API_KEY_PRESENT%"=="1" (
  call :log_info "LLM API key detected in python\config\settings.json"
  exit /b 0
)
set "LLM_API_KEY_VALUE="
for /f "usebackq tokens=1,* delims==" %%K in ("%PYTHON_ENV_FILE%") do (
  if /I "%%~K"=="LLM_API_KEY" set "LLM_API_KEY_VALUE=%%~L"
)
if not defined LLM_API_KEY_VALUE (
  call :log_info "LLM_API_KEY is empty by default. Configure it in the Settings LLM panel or import an LLM profile when your provider requires a key."
  exit /b 0
)
if /I "%LLM_API_KEY_VALUE%"=="sk-your-key-here" call :warn "LLM_API_KEY still uses the template placeholder. Chat and LLM-to-Pet validation will not work."
if /I "%LLM_API_KEY_VALUE%"=="your-api-key" call :warn "LLM_API_KEY still uses a placeholder value. Chat and LLM-to-Pet validation will not work."
exit /b 0

:detect_settings_llm_api_key
set "SETTINGS_LLM_API_KEY_PRESENT=0"
if not exist "%PYTHON_SETTINGS_FILE%" exit /b 0
for /f "usebackq delims=" %%V in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $settings = Get-Content -LiteralPath $env:PYTHON_SETTINGS_FILE -Raw | ConvertFrom-Json; $key = [string]$settings.llm.api_key; if ($key.Trim().Length -gt 0) { '1' } else { '0' } } catch { '0' }" 2^>nul`) do set "SETTINGS_LLM_API_KEY_PRESENT=%%V"
exit /b 0

:ensure_project_integrity
call :log_info "Checking electron node_modules..."
if not exist "%ELECTRON_NODE_MODULES%" (
  call :fail "electron\node_modules missing. Run: cd electron && npm install"
  exit /b 1
)

call :log_info "Checking Electron critical packages..."
if not exist "%ELECTRON_NODE_MODULES%\electron\package.json" (
  call :fail "Missing electron dependency under electron\node_modules."
  exit /b 1
)
if not exist "%ELECTRON_NODE_MODULES%\vite\package.json" (
  call :fail "Missing vite dependency under electron\node_modules."
  exit /b 1
)
if not exist "%ELECTRON_NODE_MODULES%\concurrently\package.json" (
  call :fail "Missing concurrently dependency under electron\node_modules."
  exit /b 1
)
if not exist "%ELECTRON_NODE_MODULES%\wait-on\package.json" (
  call :fail "Missing wait-on dependency under electron\node_modules."
  exit /b 1
)

call :log_info "Checking Python runtime dependencies..."
"%PYTHON_EXE%" -c "import fastapi, uvicorn" >nul 2>nul
if errorlevel 1 (
  call :fail "Python runtime dependencies are not importable (fastapi/uvicorn). Run install.bat full"
  exit /b 1
)
call :log_info "Core runtime import check passed"

"%PYTHON_EXE%" -c "import importlib.util; raise SystemExit(0 if importlib.util.find_spec('sentence_transformers') else 1)" >nul 2>nul
if errorlevel 1 (
  call :warn "sentence-transformers is not installed. Semantic memory features will be unavailable."
) else (
  call :log_info "sentence-transformers package detected; heavyweight import is deferred to the backend"
)

call :log_info "Checking backend ASR stack..."
"%PYTHON_EXE%" -c "import importlib.util; raise SystemExit(0 if importlib.util.find_spec('sherpa_onnx') else 1)" >nul 2>nul
if errorlevel 1 (
  call :warn "sherpa-onnx is not installed. Local ONNX ASR provider will be unavailable."
) else (
  call :log_info "ASR package sherpa-onnx detected; native import is deferred to the backend"
)
call :log_info "FunASR/SenseVoice service mode uses ASR_BASE_URL and is not installed into the main venv."

call :log_info "Checking backend TTS stack (Genie-TTS)..."
"%PYTHON_EXE%" -c "import importlib.metadata; importlib.metadata.version('genie-tts')" >nul 2>nul
if errorlevel 1 (
  if "%NO_OPTIONAL_INSTALL%"=="1" (
    call :warn "genie-tts not installed. TTS voice output may be disabled."
  ) else (
    call :warn "genie-tts not installed. Auto-installing Genie-TTS dependency..."
    "%PYTHON_EXE%" -m pip install genie-tts
    if errorlevel 1 (
      call :warn "genie-tts install failed. TTS voice output will be disabled."
    ) else (
      call :log_info "genie-tts installed successfully"
    )
  )
) else (
  call :log_info "TTS package genie-tts detected; heavyweight import is deferred to the backend"
)

call :log_info "Checking backend SVC stack..."
call :log_info "SoulX-Singer-SVC runs as an external Docker service via SVC_BASE_URL and is not installed into the main venv."

call :ok "Dependency availability check passed"
exit /b 0

:validate_startup_paths
call :log_info "Validating startup script paths..."
for %%L in (select_control_port select_backend_port check_backend_port start_backend start_renderer start_electron wait_for_control_server) do (
  findstr /b /l /c:":%%L" "%~f0" >nul 2>nul
  if errorlevel 1 (
    call :fail "Startup script is incomplete: missing batch label :%%L in %~f0. Close old terminals and rerun the current start.bat."
    exit /b 1
  )
)
if not exist "%RUN_BACKEND_SCRIPT%" (
  call :fail "Backend runner script missing: %RUN_BACKEND_SCRIPT%"
  exit /b 1
)
if not exist "%RUN_ELECTRON_SCRIPT%" (
  call :fail "Electron dev runner script missing: %RUN_ELECTRON_SCRIPT%"
  exit /b 1
)
if not exist "%RUN_RENDERER_SCRIPT%" (
  call :fail "Renderer runner script missing: %RUN_RENDERER_SCRIPT%"
  exit /b 1
)
if not exist "%RUN_ELECTRON_APP_SCRIPT%" (
  call :fail "Electron app runner script missing: %RUN_ELECTRON_APP_SCRIPT%"
  exit /b 1
)
if not exist "%ELECTRON_DIR%\src\renderer\index.html" (
  call :fail "Renderer entry missing: %ELECTRON_DIR%\src\renderer\index.html"
  exit /b 1
)
if not exist "%ELECTRON_NODE_MODULES%\.bin\electron.cmd" (
  call :fail "Electron command missing: %ELECTRON_NODE_MODULES%\.bin\electron.cmd"
  exit /b 1
)
if "%WITH_MCP%"=="1" if not exist "%RUN_MCP_SCRIPT%" (
  call :fail "MCP runner script missing: %RUN_MCP_SCRIPT%"
  exit /b 1
)
if "%WITH_MCP%"=="1" if not exist "%NODE_MCP_DIR%\server.mjs" (
  call :fail "MCP server entry missing: %NODE_MCP_DIR%\server.mjs"
  exit /b 1
)
if not exist "%ENSURE_QDRANT_DOCKER_SCRIPT%" (
  call :fail "Qdrant Docker helper missing: %ENSURE_QDRANT_DOCKER_SCRIPT%"
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%ENSURE_QDRANT_DOCKER_SCRIPT%" -ProjectRoot "%SCRIPT_DIR%" -SettingsPath "%PYTHON_SETTINGS_FILE%" -EnvPath "%PYTHON_ENV_FILE%" -CheckOnly
if errorlevel 1 (
  call :fail "Qdrant Docker helper self-check failed"
  exit /b 1
)
call "%RUN_BACKEND_SCRIPT%" --check
if errorlevel 1 (
  call :fail "Backend runner self-check failed"
  exit /b 1
)
call "%RUN_ELECTRON_SCRIPT%" --check
if errorlevel 1 (
  call :fail "Electron dev runner self-check failed"
  exit /b 1
)
call "%RUN_RENDERER_SCRIPT%" --check
if errorlevel 1 (
  call :fail "Renderer runner self-check failed"
  exit /b 1
)
if exist "%ELECTRON_DIR%\dist\main\index.js" (
  call "%RUN_ELECTRON_APP_SCRIPT%" --check
  if errorlevel 1 (
    call :fail "Electron app runner self-check failed"
    exit /b 1
  )
) else (
  call :log_info "Electron app runner check deferred until after build"
)
if "%WITH_MCP%"=="1" (
  call "%RUN_MCP_SCRIPT%" --check
  if errorlevel 1 (
    call :fail "MCP runner self-check failed"
    exit /b 1
  )
)
call :ok "Startup script path validation passed"
exit /b 0

:build_frontend_ui
if not exist "%ELECTRON_DIR%\vite.config.ts" (
  call :fail "Frontend build config missing: %ELECTRON_DIR%\vite.config.ts"
  exit /b 1
)

pushd "%ELECTRON_DIR%" >nul
if "%DEV_RENDERER%"=="1" (
  call :log_info "Building Electron main process only (npm run build:electron)..."
  call npm run build:electron
) else (
  call :log_info "Building frontend UI and Electron main process (npm run build)..."
  call npm run build
)
if errorlevel 1 (
  popd >nul
  call :fail "Electron/frontend build failed. Fix build errors before startup."
  exit /b 1
)
popd >nul

if not exist "%ELECTRON_DIR%\dist\main\index.js" (
  call :fail "Electron build output missing: %ELECTRON_DIR%\dist\main\index.js"
  exit /b 1
)
if "%DEV_RENDERER%"=="0" if not exist "%ELECTRON_DIR%\dist\renderer\index.html" (
  call :fail "Frontend build output missing: %ELECTRON_DIR%\dist\renderer\index.html"
  exit /b 1
)

call :ok "Frontend UI build completed"
exit /b 0

:ensure_embedding_model
set "EMBEDDING_CACHE_DIR=%PYTHON_DIR%\.cache\huggingface"
set "EMBEDDING_MODEL_LOCAL_PATH="
set "HF_HOME=%EMBEDDING_CACHE_DIR%"
set "SENTENCE_TRANSFORMERS_HOME=%EMBEDDING_CACHE_DIR%"

if not exist "%EMBEDDING_CACHE_DIR%" mkdir "%EMBEDDING_CACHE_DIR%" >nul 2>nul

call :check_model_cache "Qwen--Qwen3-Embedding-0.6B" EMBEDDING_MODEL_LOCAL_PATH
if defined EMBEDDING_MODEL_LOCAL_PATH (
  call :log_info "Embedding model cache ready"
) else (
  call :warn "Embedding model cache missing. Will download on first use (~400MB)"
)

set "ASR_CACHE_DIR=%PYTHON_DIR%\.cache\modelscope"
set "MODELSCOPE_CACHE=%ASR_CACHE_DIR%"
if not exist "%ASR_CACHE_DIR%" mkdir "%ASR_CACHE_DIR%" >nul 2>nul

set "SHERPA_SENSEVOICE_DIR=%PYTHON_DIR%\.cache\sherpa-onnx\sensevoice"
if exist "%SHERPA_SENSEVOICE_DIR%\model.int8.onnx" if exist "%SHERPA_SENSEVOICE_DIR%\tokens.txt" (
  call :log_info "sherpa-onnx SenseVoice cache ready (%SHERPA_SENSEVOICE_DIR%)"
) else (
  call :log_info "sherpa-onnx SenseVoice cache missing. Configure SHERPA_ONNX_MODEL_PATH and SHERPA_ONNX_TOKENS_PATH for local ASR."
)

set "GENIE_DATA_DIR=%PYTHON_DIR%\.cache\GenieData\GenieData"
if not exist "%GENIE_DATA_DIR%" mkdir "%GENIE_DATA_DIR%" >nul 2>nul
if exist "%GENIE_DATA_DIR%\*" (
  for /f %%F in ('dir /s /b "%GENIE_DATA_DIR%" 2^>nul ^| find /c /v ""') do set "GENIE_FILE_COUNT=%%F"
) else (
  set "GENIE_FILE_COUNT=0"
)
if %GENIE_FILE_COUNT% gtr 0 (
  call :log_info "Genie-TTS model cache ready (%GENIE_DATA_DIR%)"
) else (
  call :log_info "Genie-TTS pretrained models will download to %GENIE_DATA_DIR% on first use (~391MB)"
)
exit /b 0

:check_model_cache
set "MODEL_DIR=%EMBEDDING_CACHE_DIR%\models--%~1"
set "MODEL_DIR_ALT=%EMBEDDING_CACHE_DIR%\hub\models--%~1"
if not exist "%MODEL_DIR%" if exist "%MODEL_DIR_ALT%" set "MODEL_DIR=%MODEL_DIR_ALT%"
if not exist "%MODEL_DIR%" exit /b 0
if not exist "%MODEL_DIR%\refs\main" exit /b 0
for /f "usebackq delims=" %%R in ("%MODEL_DIR%\refs\main") do (
  if exist "%MODEL_DIR%\snapshots\%%R" set "%~2=%MODEL_DIR%\snapshots\%%R"
  exit /b 0
)
exit /b 0

:ensure_qdrant_docker
if not exist "%ENSURE_QDRANT_DOCKER_SCRIPT%" (
  call :fail "Qdrant Docker helper missing: %ENSURE_QDRANT_DOCKER_SCRIPT%"
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%ENSURE_QDRANT_DOCKER_SCRIPT%" -ProjectRoot "%SCRIPT_DIR%" -SettingsPath "%PYTHON_SETTINGS_FILE%" -EnvPath "%PYTHON_ENV_FILE%"
if errorlevel 1 (
  call :fail "Qdrant Docker auto-start failed. Disable with --no-qdrant or set QDRANT_AUTO_START=0."
  exit /b 1
)
exit /b 0

:select_control_port
call :log_info "Selecting Electron control port; preferred=%CONTROL_SERVER_PORT%, fallback=%CONTROL_SERVER_PORT_FALLBACKS%"
set "SELECTED_CONTROL_PORT="
set "CONTROL_PORT_SELECTION_STATUS="
for /f "tokens=1,2 delims=|" %%P in ('powershell -NoProfile -ExecutionPolicy Bypass -File "%SELECT_STARTUP_PORT_SCRIPT%" -Mode control -PreferredPort %CONTROL_SERVER_PORT% -FallbackPorts "%CONTROL_SERVER_PORT_FALLBACKS%" -ProjectRoot "%SCRIPT_DIR%"') do (
  set "SELECTED_CONTROL_PORT=%%P"
  set "CONTROL_PORT_SELECTION_STATUS=%%Q"
)
if not defined SELECTED_CONTROL_PORT (
  call :fail "Unable to inspect Electron control port availability."
  exit /b 1
)
if /I "%CONTROL_PORT_SELECTION_STATUS%"=="blocked" (
  call :fail "Electron control ports are occupied. Stop old Yuizaki Electron windows or set CONTROL_SERVER_PORT before launching."
  exit /b 1
)
if not "%SELECTED_CONTROL_PORT%"=="%CONTROL_SERVER_PORT%" (
  call :warn "Preferred control port %CONTROL_SERVER_PORT% is occupied. Using fallback port %SELECTED_CONTROL_PORT% for this startup."
  set "CONTROL_SERVER_PORT=%SELECTED_CONTROL_PORT%"
  call :refresh_control_urls
  call :refresh_renderer_urls
)
if /I "%CONTROL_PORT_SELECTION_STATUS%"=="free" call :log_info "Control port is free: %PANEL_URL%"
if /I "%CONTROL_PORT_SELECTION_STATUS%"=="freed" call :log_info "Cleared stale Yuizaki control process and will reuse port: %PANEL_URL%"
if /I "%CONTROL_PORT_SELECTION_STATUS%"=="fallback" call :log_info "Fallback control port selected: %PANEL_URL%"
if "%DEV_RENDERER%"=="1" (
  call :log_info "Selecting renderer port; preferred=%RENDERER_PORT%, fallback=%RENDERER_PORT_FALLBACKS%"
  set "SELECTED_RENDERER_PORT="
  set "RENDERER_PORT_SELECTION_STATUS="
  for /f "tokens=1,2 delims=|" %%R in ('powershell -NoProfile -ExecutionPolicy Bypass -File "%SELECT_STARTUP_PORT_SCRIPT%" -Mode renderer -PreferredPort %RENDERER_PORT% -FallbackPorts "%RENDERER_PORT_FALLBACKS%" -ProjectRoot "%SCRIPT_DIR%"') do (
    set "SELECTED_RENDERER_PORT=%%R"
    set "RENDERER_PORT_SELECTION_STATUS=%%S"
  )
  if not defined SELECTED_RENDERER_PORT (
    call :fail "Unable to inspect renderer port availability."
    exit /b 1
  )
  if /I "!RENDERER_PORT_SELECTION_STATUS!"=="blocked" (
    call :fail "Renderer ports are occupied. Stop old Yuizaki renderer windows or set RENDERER_PORT before launching."
    exit /b 1
  )
  if not "!SELECTED_RENDERER_PORT!"=="%RENDERER_PORT%" (
    call :warn "Preferred renderer port %RENDERER_PORT% is occupied. Using fallback port !SELECTED_RENDERER_PORT! for this startup."
    set "RENDERER_PORT=!SELECTED_RENDERER_PORT!"
    call :refresh_control_urls
    call :refresh_renderer_urls
  )
  if /I "!RENDERER_PORT_SELECTION_STATUS!"=="free" call :log_info "Renderer port is free: !RENDERER_URL!"
  if /I "!RENDERER_PORT_SELECTION_STATUS!"=="freed" call :log_info "Cleared stale Yuizaki renderer process and will reuse port: !RENDERER_URL!"
  if /I "!RENDERER_PORT_SELECTION_STATUS!"=="fallback" call :log_info "Fallback renderer port selected: !RENDERER_URL!"
)
exit /b 0

:select_backend_port
call :log_info "Selecting backend port; preferred=%SERVER_PORT%, fallback=%SERVER_PORT_FALLBACKS%"
set "SELECTED_SERVER_PORT="
set "PORT_SELECTION_STATUS="
for /f "tokens=1,2 delims=|" %%P in ('powershell -NoProfile -ExecutionPolicy Bypass -File "%SELECT_STARTUP_PORT_SCRIPT%" -Mode backend -PreferredPort %SERVER_PORT% -FallbackPorts "%SERVER_PORT_FALLBACKS%" -ProjectRoot "%SCRIPT_DIR%"') do (
  set "SELECTED_SERVER_PORT=%%P"
  set "PORT_SELECTION_STATUS=%%Q"
)
if not defined SELECTED_SERVER_PORT (
  call :fail "Unable to inspect backend port availability."
  exit /b 1
)
if /I "%PORT_SELECTION_STATUS%"=="blocked" (
  call :fail "Backend ports are occupied but no healthy Yuizaki backend responded to /api/ping. Stop the old backend windows or set SERVER_PORT before launching."
  exit /b 1
)
if not "%SELECTED_SERVER_PORT%"=="%SERVER_PORT%" (
  call :warn "Preferred backend port %SERVER_PORT% is occupied by an unhealthy/old process. Using fallback port %SELECTED_SERVER_PORT% for this startup."
  set "SERVER_PORT=%SELECTED_SERVER_PORT%"
  call :refresh_backend_urls
)
if /I "%PORT_SELECTION_STATUS%"=="healthy" call :log_info "Healthy backend candidate selected: %BACKEND_URL%"
if /I "%PORT_SELECTION_STATUS%"=="free" call :log_info "Backend port is free: %BACKEND_URL%"
if /I "%PORT_SELECTION_STATUS%"=="freed" call :log_info "Cleared stale Yuizaki backend process and will reuse port: %BACKEND_URL%"
if /I "%PORT_SELECTION_STATUS%"=="fallback" call :log_info "Fallback backend port selected: %BACKEND_URL%"
exit /b 0

:check_backend_port
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ok=$false; try { $r=Invoke-WebRequest -Uri '%BACKEND_URL%/api/ping' -UseBasicParsing -TimeoutSec 5; if($r.StatusCode -ge 200 -and $r.StatusCode -lt 300){ $ok=$true } } catch { $null = $_ }; if($ok){ exit 10 } else { exit 0 }"
if errorlevel 10 (
  set "BACKEND_ALREADY_RUNNING=1"
  call :log_info "Detected healthy backend at %BACKEND_URL%"
) else (
  call :log_info "No healthy backend detected, a new backend process will be started"
)
exit /b 0

:adopt_existing_control_token
set "EXISTING_CONTROL_TOKEN="
set "EXISTING_BACKEND_HOST="
set "EXISTING_BACKEND_PORT="
set "EXISTING_BACKEND_ORIGIN="
set "TOKEN_TMP=%TEMP%\yuizaki-control-token-%RANDOM%%RANDOM%.txt"
if exist "%SCRIPT_DIR%\scripts\read_control_context.ps1" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%\scripts\read_control_context.ps1" -Port %CONTROL_SERVER_PORT% -OutputPath "%TOKEN_TMP%" >nul 2>nul
)
if exist "%TOKEN_TMP%" (
  for /f "usebackq tokens=1,2,3,4 delims=|" %%A in ("%TOKEN_TMP%") do (
    set "EXISTING_CONTROL_TOKEN=%%A"
    set "EXISTING_BACKEND_HOST=%%B"
    set "EXISTING_BACKEND_PORT=%%C"
    set "EXISTING_BACKEND_ORIGIN=%%D"
  )
  del /q "%TOKEN_TMP%" >nul 2>nul
)
if defined EXISTING_CONTROL_TOKEN (
  if not "%YUIZAKI_CONTROL_TOKEN%"=="%EXISTING_CONTROL_TOKEN%" call :log_info "Reusing token from existing Electron control server"
  set "YUIZAKI_CONTROL_TOKEN=%EXISTING_CONTROL_TOKEN%"
  set "YUIZAKI_BACKEND_API_TOKEN=%EXISTING_CONTROL_TOKEN%"
  if defined EXISTING_BACKEND_PORT (
    if defined EXISTING_BACKEND_HOST set "SERVER_HOST=%EXISTING_BACKEND_HOST%"
    set "SERVER_PORT=%EXISTING_BACKEND_PORT%"
    call :refresh_backend_urls
    if defined EXISTING_BACKEND_ORIGIN call :log_info "Using backend origin reported by existing control server: %EXISTING_BACKEND_ORIGIN%"
  )
  call :build_panel_open_url
)
exit /b 0

:check_backend_auth_alignment
call :log_info "Checking existing backend API token alignment..."
powershell -NoProfile -ExecutionPolicy Bypass -Command "$headers=@{}; $token=$env:YUIZAKI_BACKEND_API_TOKEN; if($token){ $headers['Authorization']='Bearer ' + $token; $headers['x-yuizaki-backend-token']=$token }; try { $r=Invoke-WebRequest -Uri '%BACKEND_URL%/api/readiness' -Headers $headers -UseBasicParsing -TimeoutSec 5; if($r.StatusCode -ge 200 -and $r.StatusCode -lt 300){ exit 0 }; exit 1 } catch { $status=$null; try { $status=[int]$_.Exception.Response.StatusCode } catch { }; if($status -eq 401 -or $status -eq 403){ exit 2 }; exit 1 }"
if errorlevel 2 (
  call :warn "Detected a Yuizaki backend with a different API token. Attempting to stop the project-owned stale backend and restart it for this session."
  call :stop_mismatched_backend
  if errorlevel 1 exit /b 1
  set "BACKEND_ALREADY_RUNNING=0"
  call :log_info "Stale backend stopped. A new backend will be launched with the current startup token."
  exit /b 0
)
if errorlevel 1 (
  call :warn "Could not verify existing backend API token alignment; continuing because readiness is reachable."
  exit /b 0
)
call :ok "Existing backend API token alignment passed"
exit /b 0

:stop_mismatched_backend
set "STOPPED_BACKEND_PORT="
set "STOPPED_BACKEND_STATUS="
for /f "tokens=1,2 delims=|" %%P in ('powershell -NoProfile -ExecutionPolicy Bypass -File "%SELECT_STARTUP_PORT_SCRIPT%" -Mode stop-backend -PreferredPort %SERVER_PORT% -ProjectRoot "%SCRIPT_DIR%"') do (
  set "STOPPED_BACKEND_PORT=%%P"
  set "STOPPED_BACKEND_STATUS=%%Q"
)
if not defined STOPPED_BACKEND_PORT (
  call :fail "Unable to inspect or stop the mismatched backend on %BACKEND_URL%."
  exit /b 1
)
if /I not "%STOPPED_BACKEND_STATUS%"=="stopped" (
  call :fail "Existing backend on %BACKEND_URL% uses a different token and could not be proven as a project-owned Yuizaki process. Stop it manually or set SERVER_PORT to another free port."
  exit /b 1
)
exit /b 0

:stop_stale_control_server
set "STOPPED_CONTROL_PORT="
set "STOPPED_CONTROL_STATUS="
for /f "tokens=1,2 delims=|" %%P in ('powershell -NoProfile -ExecutionPolicy Bypass -File "%SELECT_STARTUP_PORT_SCRIPT%" -Mode stop-control -PreferredPort %CONTROL_SERVER_PORT% -ProjectRoot "%SCRIPT_DIR%"') do (
  set "STOPPED_CONTROL_PORT=%%P"
  set "STOPPED_CONTROL_STATUS=%%Q"
)
if not defined STOPPED_CONTROL_PORT (
  call :fail "Unable to inspect or stop the stale Electron control server on http://%SERVER_HOST%:%CONTROL_SERVER_PORT%."
  exit /b 1
)
if /I not "%STOPPED_CONTROL_STATUS%"=="stopped" (
  call :fail "The control port is owned by a process that could not be proven as a Yuizaki Electron window. Stop it manually or set CONTROL_SERVER_PORT to another free port."
  exit /b 1
)
exit /b 0

:start_backend
call :log_info "Launching backend terminal..."
if not exist "%RUN_BACKEND_SCRIPT%" (
  call :fail "Backend runner script missing: %RUN_BACKEND_SCRIPT%"
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath 'cmd.exe' -ArgumentList '/d','/k','title Yuizaki Backend && echo [INFO] Backend terminal is visible. Logs are also printed here. && call \"%RUN_BACKEND_SCRIPT%\"' -WorkingDirectory '%PYTHON_DIR%' -WindowStyle Normal"
if errorlevel 1 (
  call :fail "Failed to launch backend terminal"
  exit /b 1
)
call :ok "Backend launch command sent"
exit /b 0

:wait_for_backend
call :log_info "Waiting for backend: %BACKEND_URL%/api/ping (max %MAX_BACKEND_WAIT_SECONDS%s)..."
powershell -NoProfile -ExecutionPolicy Bypass -Command "$deadline=(Get-Date).AddSeconds(%MAX_BACKEND_WAIT_SECONDS%); $ok=$false; while((Get-Date) -lt $deadline){ try { $r=Invoke-WebRequest -Uri '%BACKEND_URL%/api/ping' -UseBasicParsing -TimeoutSec 5; if($r.StatusCode -ge 200 -and $r.StatusCode -lt 300){ $ok=$true; break } } catch { $null = $_ } Start-Sleep -Milliseconds 2000 }; if($ok){ exit 0 } else { exit 1 }"
if errorlevel 1 (
  call :fail "Backend failed to become healthy within %MAX_BACKEND_WAIT_SECONDS%s. Check %LOG_DIR%\python.log"
  exit /b 1
)
call :ok "Backend is responding"
exit /b 0

:check_database_migrations
call :log_info "Checking database revision against Alembic head..."
pushd "%PYTHON_DIR%" >nul
"%PYTHON_EXE%" migration_check.py >nul 2>nul
if errorlevel 1 (
  popd >nul
  call :warn "Database schema is not at Alembic head. Backend will auto-migrate on startup."
  exit /b 0
)
popd >nul
call :ok "Database migration check passed"
exit /b 0

:run_verify_suite
call :run_python_typecheck
if errorlevel 1 exit /b 1
call :run_python_tests
if errorlevel 1 exit /b 1
call :run_electron_typecheck
if errorlevel 1 exit /b 1
call :run_electron_build
if errorlevel 1 exit /b 1
call :run_electron_tests
if errorlevel 1 exit /b 1
exit /b 0

:run_python_typecheck
call :log_info "Running Python type check (basedpyright python)..."
"%PYTHON_EXE%" -m basedpyright python
if errorlevel 1 (
  call :fail "Python type check failed"
  exit /b 1
)
call :ok "Python type check passed"
exit /b 0

:run_python_tests
call :log_info "Running Python tests (pytest . --ignore=.venv)..."
pushd "%PYTHON_DIR%" >nul
"%PYTHON_EXE%" -m pytest . --ignore=.venv
if errorlevel 1 (
  popd >nul
  call :fail "Python tests failed"
  exit /b 1
)
popd >nul
call :ok "Python tests passed"
exit /b 0

:run_electron_typecheck
call :log_info "Running Electron type check (npm run type-check)..."
pushd "%ELECTRON_DIR%" >nul
call npm run type-check
if errorlevel 1 (
  popd >nul
  call :fail "Electron type check failed"
  exit /b 1
)
popd >nul
call :ok "Electron type check passed"
exit /b 0

:run_electron_build
call :log_info "Running Electron build (npm run build)..."
pushd "%ELECTRON_DIR%" >nul
call npm run build
if errorlevel 1 (
  popd >nul
  call :fail "Electron build failed"
  exit /b 1
)
popd >nul
call :ok "Electron build passed"
exit /b 0

:run_electron_tests
call :log_info "Running Electron tests (npm test)..."
pushd "%ELECTRON_DIR%" >nul
call npm test
if errorlevel 1 (
  popd >nul
  call :fail "Electron tests failed"
  exit /b 1
)
popd >nul
call :ok "Electron tests passed"
exit /b 0

:start_renderer
call :log_info "Starting Vite dev server..."
if not exist "%ELECTRON_DIR%\src\renderer\index.html" (
  call :fail "Renderer entry missing: %ELECTRON_DIR%\src\renderer\index.html"
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ok=$false; try { $r=Invoke-WebRequest -Uri '%RENDERER_URL%' -UseBasicParsing -TimeoutSec 2; if($r.StatusCode -eq 200){ $ok=$true } } catch { $null = $_ }; if($ok){ exit 10 } else { exit 0 }"
if errorlevel 10 (
  call :log_info "Reusing existing renderer: %RENDERER_URL%"
  exit /b 0
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath 'cmd.exe' -ArgumentList '/d','/k','title Yuizaki Renderer && echo [INFO] Renderer terminal is visible. && call \"%RUN_RENDERER_SCRIPT%\"' -WorkingDirectory '%ELECTRON_DIR%' -WindowStyle Normal"
if errorlevel 1 (
  call :fail "Failed to launch Vite dev server"
  exit /b 1
)
call :ok "Renderer launch command sent"
exit /b 0

:wait_for_renderer
call :log_info "Waiting for renderer: %RENDERER_URL%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$deadline=(Get-Date).AddSeconds(120); $ok=$false; while((Get-Date) -lt $deadline){ try { $r=Invoke-WebRequest -Uri '%RENDERER_URL%' -UseBasicParsing -TimeoutSec 2; if($r.StatusCode -eq 200){ $ok=$true; break } } catch { $null = $_ } Start-Sleep -Milliseconds 1000 }; if($ok){ exit 0 } else { exit 1 }"
if errorlevel 1 (
  call :fail "Renderer failed to serve on %RENDERER_URL%. Check Electron/Vite console."
  exit /b 1
)
call :ok "Renderer endpoint is responding"
exit /b 0

:start_electron
call :log_info "Launching Electron..."
if not exist "%ELECTRON_DIR%\dist\main\index.js" (
  call :fail "Electron build missing: %ELECTRON_DIR%\dist\main\index.js"
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath 'cmd.exe' -ArgumentList '/d','/k','title Yuizaki Electron && echo [INFO] Electron terminal is visible. && call \"%RUN_ELECTRON_APP_SCRIPT%\"' -WorkingDirectory '%ELECTRON_DIR%' -WindowStyle Normal"
if errorlevel 1 (
  call :fail "Failed to launch Electron"
  exit /b 1
)
call :ok "Electron launch command sent"
exit /b 0

:wait_for_control_server
call :log_info "Waiting for control server: http://%SERVER_HOST%:%CONTROL_SERVER_PORT%/api/health (max %MAX_CONTROL_WAIT_SECONDS%s)"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$deadline=(Get-Date).AddSeconds(%MAX_CONTROL_WAIT_SECONDS%); $ok=$false; $targets=@('http://%SERVER_HOST%:%CONTROL_SERVER_PORT%/api/health','http://127.0.0.1:%CONTROL_SERVER_PORT%/api/health') | Select-Object -Unique; while((Get-Date) -lt $deadline){ foreach($uri in $targets){ try { $r=Invoke-WebRequest -Uri $uri -UseBasicParsing -TimeoutSec 3; if($r.StatusCode -eq 200){ $body=$r.Content | ConvertFrom-Json; if([string]($body.status) -eq 'ok'){ $ok=$true; break } } } catch { $null = $_ } }; if($ok){ break }; Start-Sleep -Milliseconds 1000 }; if($ok){ exit 0 } else { exit 1 }"
if errorlevel 1 (
  call :fail "Control server failed on http://%SERVER_HOST%:%CONTROL_SERVER_PORT%/api/health within %MAX_CONTROL_WAIT_SECONDS%s"
  exit /b 1
)
call :ok "Control server is responding"
exit /b 0

:verify_control_backend_link_or_restart_control
call :verify_control_backend_link
if not errorlevel 1 exit /b 0
call :warn "The control server is stale or bound to a dead backend. Restarting the project-owned Electron control window and retrying once."
call :stop_stale_control_server
if errorlevel 1 exit /b 1
call :start_electron
if errorlevel 1 exit /b 1
call :wait_for_control_server
if errorlevel 1 exit /b 1
call :adopt_existing_control_token
call :verify_control_backend_link
if errorlevel 1 exit /b 1
exit /b 0

:verify_control_backend_link
call :log_info "Verifying control server backend proxy: http://%SERVER_HOST%:%CONTROL_SERVER_PORT%/api/ping"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$headers=@{}; $token=$env:YUIZAKI_CONTROL_TOKEN; if(-not $token){ $token=$env:YUIZAKI_BACKEND_API_TOKEN }; if($token){ $headers['Authorization']='Bearer ' + $token; $headers['x-yuizaki-backend-token']=$token }; try { $r=Invoke-WebRequest -Uri ('http://' + $env:SERVER_HOST + ':' + $env:CONTROL_SERVER_PORT + '/api/ping') -Headers $headers -UseBasicParsing -TimeoutSec 12; if($r.StatusCode -ge 200 -and $r.StatusCode -lt 300){ $body=$r.Content | ConvertFrom-Json; if($body.ok -eq $true -or [string]$body.status -eq 'ok' -or [string]$body.status -eq 'healthy'){ exit 0 } }; exit 1 } catch { exit 1 }"
if not errorlevel 1 (
  call :ok "Control server can reach the backend"
  exit /b 0
)
call :warn "Control server is up, but its backend proxy is not healthy. Restarting backend and retrying once."
set "BACKEND_ALREADY_RUNNING=0"
call :select_backend_port
if errorlevel 1 exit /b 1
call :check_backend_port
if errorlevel 1 exit /b 1
if "%BACKEND_ALREADY_RUNNING%"=="0" (
  call :start_backend
  if errorlevel 1 exit /b 1
  call :wait_for_backend
  if errorlevel 1 exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$headers=@{}; $token=$env:YUIZAKI_CONTROL_TOKEN; if(-not $token){ $token=$env:YUIZAKI_BACKEND_API_TOKEN }; if($token){ $headers['Authorization']='Bearer ' + $token; $headers['x-yuizaki-backend-token']=$token }; try { $r=Invoke-WebRequest -Uri ('http://' + $env:SERVER_HOST + ':' + $env:CONTROL_SERVER_PORT + '/api/ping') -Headers $headers -UseBasicParsing -TimeoutSec 12; if($r.StatusCode -ge 200 -and $r.StatusCode -lt 300){ $body=$r.Content | ConvertFrom-Json; if($body.ok -eq $true -or [string]$body.status -eq 'ok' -or [string]$body.status -eq 'healthy'){ exit 0 } }; exit 1 } catch { exit 1 }"
if errorlevel 1 (
  call :fail "Control server is responding, but it still cannot reach the Python backend. Check the visible Backend terminal and %LOG_DIR%\python.log."
  exit /b 1
)
call :ok "Control server can reach the backend after backend restart"
exit /b 0

:ensure_pet_visible
call :log_info "Ensuring desktop pet layer is visible..."
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $base='http://' + $env:SERVER_HOST + ':' + $env:CONTROL_SERVER_PORT; $headers=@{}; $token=$env:YUIZAKI_CONTROL_TOKEN; if(-not $token){ $token=$env:YUIZAKI_BACKEND_API_TOKEN }; if($token){ $headers['Authorization']='Bearer ' + $token; $headers['x-yuizaki-backend-token']=$token }; function Invoke-Control($Path,$Body){ $json=$Body | ConvertTo-Json -Compress; $r=Invoke-WebRequest -Uri ($base + $Path) -Headers $headers -Method POST -Body $json -ContentType 'application/json' -UseBasicParsing -TimeoutSec 8; if($r.StatusCode -lt 200 -or $r.StatusCode -ge 300){ throw ('control request failed: ' + $Path) } }; Invoke-Control '/api/pet/visibility' @{visible=$true}; Invoke-Control '/api/pet/opacity' @{opacity=1}; Invoke-Control '/api/pet/scale' @{scale=0.32}; Invoke-Control '/api/pet/dock' @{}; Start-Sleep -Milliseconds 700; $diag=Invoke-RestMethod -Uri ($base + '/api/system/diagnostics') -Headers $headers -TimeoutSec 8; if(($diag.petOverlayVisible -ne $true) -or ($diag.petState.visible -ne $true) -or ($diag.petOverlayHasVisiblePixels -eq $false)){ Invoke-Control '/api/pet/reload' @{}; Start-Sleep -Milliseconds 1000; Invoke-Control '/api/pet/visibility' @{visible=$true}; Invoke-Control '/api/pet/opacity' @{opacity=1}; Invoke-Control '/api/pet/scale' @{scale=0.32}; Invoke-Control '/api/pet/dock' @{} }; exit 0"
if errorlevel 1 (
  call :fail "Control server responded, but the desktop pet layer could not be restored."
  exit /b 1
)
call :ok "Desktop pet layer is visible and restored"
exit /b 0

:smoke_core_endpoints
call :adopt_existing_control_token
call :smoke_get "http://%SERVER_HOST%:%CONTROL_SERVER_PORT%/api/ping" "Python ping via control server"
if errorlevel 1 exit /b 1
call :smoke_get "http://%SERVER_HOST%:%CONTROL_SERVER_PORT%/health" "Python health via control server"
if errorlevel 1 exit /b 1
call :smoke_get "http://%SERVER_HOST%:%CONTROL_SERVER_PORT%/api/readiness" "Python readiness via control server"
if errorlevel 1 exit /b 1
call :smoke_get "http://%SERVER_HOST%:%CONTROL_SERVER_PORT%/api/companions" "Companion list via control server"
if errorlevel 1 exit /b 1
call :smoke_get "http://%SERVER_HOST%:%CONTROL_SERVER_PORT%/api/pet/state" "Pet state"
if errorlevel 1 exit /b 1
call :smoke_get "http://%SERVER_HOST%:%CONTROL_SERVER_PORT%/api/pet/catalog" "Pet catalog"
if errorlevel 1 exit /b 1
call :smoke_post_json "http://%SERVER_HOST%:%CONTROL_SERVER_PORT%/api/pet/control-directive" "{}" "Pet control directive"
if errorlevel 1 exit /b 1
if "%WITH_MCP%"=="1" (
  call :smoke_get "%MCP_URL%/health" "MCP health"
  if errorlevel 1 exit /b 1
)
call :ok "Lightweight smoke checks passed"
exit /b 0

:smoke_get
powershell -NoProfile -ExecutionPolicy Bypass -Command "$headers=@{}; $token=$env:YUIZAKI_CONTROL_TOKEN; if(-not $token){ $token=$env:YUIZAKI_BACKEND_API_TOKEN }; if($token){ $headers['Authorization']='Bearer ' + $token; $headers['x-yuizaki-backend-token']=$token }; $deadline=(Get-Date).AddSeconds(30); $last=''; while((Get-Date) -lt $deadline){ try { $r=Invoke-WebRequest -Uri '%~1' -Headers $headers -UseBasicParsing -TimeoutSec 12; if($r.StatusCode -ge 200 -and $r.StatusCode -lt 300){ exit 0 }; $last='HTTP ' + $r.StatusCode } catch { $last=$_.Exception.Message }; Start-Sleep -Milliseconds 1000 }; Write-Error $last; exit 1"
if errorlevel 1 (
  call :fail "Smoke check failed: %~2 (%~1)"
  exit /b 1
)
call :log_info "Smoke OK: %~2"
exit /b 0

:smoke_post_json
powershell -NoProfile -ExecutionPolicy Bypass -Command "$headers=@{}; $token=$env:YUIZAKI_CONTROL_TOKEN; if(-not $token){ $token=$env:YUIZAKI_BACKEND_API_TOKEN }; if($token){ $headers['Authorization']='Bearer ' + $token; $headers['x-yuizaki-backend-token']=$token }; $deadline=(Get-Date).AddSeconds(30); $last=''; while((Get-Date) -lt $deadline){ try { $r=Invoke-WebRequest -Uri '%~1' -Headers $headers -Method POST -Body '%~2' -ContentType 'application/json' -UseBasicParsing -TimeoutSec 12; if($r.StatusCode -ge 200 -and $r.StatusCode -lt 300){ exit 0 }; $last='HTTP ' + $r.StatusCode } catch { $last=$_.Exception.Message }; Start-Sleep -Milliseconds 1000 }; Write-Error $last; exit 1"
if errorlevel 1 (
  call :fail "Smoke check failed: %~3 (%~1)"
  exit /b 1
)
call :log_info "Smoke OK: %~3"
exit /b 0

:start_mcp
call :log_info "Starting MCP service..."
if not exist "%RUN_MCP_SCRIPT%" (
  call :fail "MCP runner script not found: %RUN_MCP_SCRIPT%. Use --no-mcp only when you intentionally disable MCP."
  exit /b 1
)
if not exist "%NODE_MCP_DIR%\node_modules" (
  call :fail "node-mcp dependencies missing. Run: cd node-mcp && npm install, or start with --no-mcp to disable MCP."
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ok=$false; try { $r=Invoke-WebRequest -Uri '%MCP_URL%/health' -UseBasicParsing -TimeoutSec 8; if($r.StatusCode -eq 200){ $body=$r.Content | ConvertFrom-Json; if($body.ok -eq $true){ $ok=$true } } } catch { $null = $_ }; if($ok){ exit 10 } else { exit 0 }"
if errorlevel 10 (
  call :log_info "Reusing existing MCP service: %MCP_URL%"
  exit /b 0
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath 'cmd.exe' -ArgumentList '/d','/k','title Yuizaki MCP && echo [INFO] MCP terminal is visible. && call \"%RUN_MCP_SCRIPT%\"' -WorkingDirectory '%NODE_MCP_DIR%' -WindowStyle Normal"
if errorlevel 1 (
  call :fail "Failed to launch MCP service"
  exit /b 1
)
call :ok "MCP service launch command sent (port 7777)"
exit /b 0

:wait_for_mcp
call :log_info "Waiting for MCP service: %MCP_URL%/health"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$deadline=(Get-Date).AddSeconds(120); $ok=$false; while((Get-Date) -lt $deadline){ try { $r=Invoke-WebRequest -Uri '%MCP_URL%/health' -UseBasicParsing -TimeoutSec 8; if($r.StatusCode -eq 200){ $body=$r.Content | ConvertFrom-Json; if($body.ok -eq $true){ $ok=$true; break } } } catch { $null = $_ } Start-Sleep -Milliseconds 1000 }; if($ok){ exit 0 } else { exit 1 }"
if errorlevel 1 (
  call :fail "MCP service failed on %MCP_URL%/health"
  exit /b 1
)
call :ok "MCP service is responding"
exit /b 0

:fatal
echo.
echo ============================================================
if defined LAST_ERROR (
  call :error_msg "Startup failed: %LAST_ERROR%"
) else (
  call :error_msg "Startup failed for an unknown reason."
)
echo ============================================================
echo.
call :log_info "Troubleshooting:"
call :log_info "  1. Run install.bat full to reinstall dependencies"
call :log_info "  2. Check python\.env for API key configuration"
call :log_info "  3. Verify ports %SERVER_PORT% and %CONTROL_SERVER_PORT% are free"
call :log_info "  4. Check logs: %LOG_DIR%"
echo.
if "%NO_PAUSE%"=="1" exit /b 1
call :log_info "Press any key to exit..."
pause >nul
exit /b 1

