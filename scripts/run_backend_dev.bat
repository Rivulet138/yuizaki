@echo off
setlocal EnableExtensions EnableDelayedExpansion
for %%I in ("%~dp0..\python") do set "PYTHON_ROOT=%%~fI"
pushd "%PYTHON_ROOT%" >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Failed to enter python directory: %PYTHON_ROOT%
  exit /b 1
)

if not defined APP_ENV set "APP_ENV=development"
if not defined ENV set "ENV=development"
if not defined NODE_ENV set "NODE_ENV=development"
if not defined SERVER_HOST set "SERVER_HOST=127.0.0.1"
if not defined SERVER_BIND_HOST set "SERVER_BIND_HOST=127.0.0.1"
if not defined SERVER_PORT set "SERVER_PORT=8001"
if not defined CONTROL_SERVER_PORT set "CONTROL_SERVER_PORT=38945"
if not defined SERVER_DEBUG set "SERVER_DEBUG=true"
if not defined LOG_LEVEL set "LOG_LEVEL=DEBUG"
if not defined PYTHONUNBUFFERED set "PYTHONUNBUFFERED=1"
if not defined PYTHONIOENCODING set "PYTHONIOENCODING=utf-8"
if not defined SCHEMA_MIGRATION_MODE set "SCHEMA_MIGRATION_MODE=bootstrap"
if not defined YUIZAKI_BACKEND_AUTO_RESTART set "YUIZAKI_BACKEND_AUTO_RESTART=1"
if not defined YUIZAKI_BACKEND_RESTART_DELAY_SECONDS set "YUIZAKI_BACKEND_RESTART_DELAY_SECONDS=3"
if not defined YUIZAKI_BACKEND_API_TOKEN (
  for /f "usebackq delims=" %%T in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$bytes=New-Object byte[] 32; $rng=[Security.Cryptography.RandomNumberGenerator]::Create(); $rng.GetBytes($bytes); $rng.Dispose(); [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+','-').Replace('/','_')" 2^>nul`) do set "YUIZAKI_BACKEND_API_TOKEN=%%T"
  if not defined YUIZAKI_BACKEND_API_TOKEN set "YUIZAKI_BACKEND_API_TOKEN=yuizaki-local-%RANDOM%%RANDOM%%RANDOM%"
  echo [INFO] Generated a per-run YUIZAKI_BACKEND_API_TOKEN for local backend development.
)

if defined HF_HOME set "HF_HOME=%HF_HOME%"
if defined SENTENCE_TRANSFORMERS_HOME set "SENTENCE_TRANSFORMERS_HOME=%SENTENCE_TRANSFORMERS_HOME%"
if defined EMBEDDING_MODEL_LOCAL_PATH set "EMBEDDING_MODEL_LOCAL_PATH=%EMBEDDING_MODEL_LOCAL_PATH%"
if defined WHISPER_MODEL_LOCAL_PATH set "WHISPER_MODEL_LOCAL_PATH=%WHISPER_MODEL_LOCAL_PATH%"
if defined MODELSCOPE_CACHE set "MODELSCOPE_CACHE=%MODELSCOPE_CACHE%"
if defined GENIE_DATA_DIR set "GENIE_DATA_DIR=%GENIE_DATA_DIR%"

if /I "%~1"=="--check" (
  if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Python executable missing: %CD%\.venv\Scripts\python.exe
    exit /b 1
  )
  if not exist "app.py" (
    echo [ERROR] Backend app missing: %CD%\app.py
    exit /b 1
  )
  echo [OK] Backend runner check passed: %CD%
  exit /b 0
)

:run_backend_loop
echo [INFO] Applying database migrations...
.venv\Scripts\python.exe migration_bootstrap.py
if errorlevel 1 (
  echo [ERROR] database bootstrap / migration failed.
  exit /b 1
)

echo [INFO] Starting backend on http://%SERVER_BIND_HOST%:%SERVER_PORT%
.venv\Scripts\python.exe -m uvicorn app:app --host %SERVER_BIND_HOST% --port %SERVER_PORT% --env-file .env --log-level info
set "BACKEND_EXIT_CODE=%ERRORLEVEL%"

echo.
echo [WARN] Backend process exited with code %BACKEND_EXIT_CODE%.
if "%YUIZAKI_BACKEND_AUTO_RESTART%"=="1" (
  echo [INFO] Auto-restart is enabled. Press Ctrl+C now to stop, or wait %YUIZAKI_BACKEND_RESTART_DELAY_SECONDS%s to restart.
  timeout /t %YUIZAKI_BACKEND_RESTART_DELAY_SECONDS% /nobreak >nul
  goto :run_backend_loop
)

if "%YUIZAKI_SUPERVISOR%"=="1" exit /b %BACKEND_EXIT_CODE%
echo [INFO] Auto-restart disabled. Press any key to close this window.
pause >nul
