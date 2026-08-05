@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PROFILE=%~1"
if not defined PROFILE set "PROFILE=core"
if /I "%PROFILE%"=="core" (
  set "PY_LOCK=requirements-core-lock-windows.txt"
) else if /I "%PROFILE%"=="full" (
  set "PY_LOCK=requirements-lock-windows.txt"
) else (
  echo Usage: install.bat [core^|full]
  exit /b 2
)

call :require_cmd node || exit /b 1
call :require_cmd npm || exit /b 1
node -e "const [major, minor] = process.versions.node.split('.').map(Number); process.exit(major > 22 || (major === 22 && minor >= 13) ? 0 : 1)" >nul 2>nul
if errorlevel 1 (
  for /f %%V in ('node -p "process.versions.node" 2^>nul') do set "NODE_VERSION=%%V"
  echo [ERROR] Node.js 22.13+ is required. Current version: %NODE_VERSION%.
  exit /b 1
)
call scripts\resolve_python.bat || exit /b 1

echo [1/3] Installing Electron dependencies...
pushd electron
call npm ci
if errorlevel 1 goto :error
call npm run install:runtime
if errorlevel 1 goto :error
popd

echo [2/3] Installing node-mcp dependencies...
pushd node-mcp
call npm ci
if errorlevel 1 goto :error
popd

echo [3/3] Creating Python venv and installing %PROFILE% dependencies...
pushd python
if not exist ".venv\Scripts\python.exe" (
  %PY_CMD% -m venv .venv
  if errorlevel 1 goto :error
)

call ".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error
call ".venv\Scripts\python.exe" -m pip install -r "%PY_LOCK%"
if errorlevel 1 goto :error
call ".venv\Scripts\python.exe" -m pip check
if errorlevel 1 goto :error
call ".venv\Scripts\python.exe" scripts\check_installed_lock.py --lock "%PY_LOCK%"
if errorlevel 1 goto :error

if not exist ".env" (
  copy /y ".env.example" ".env" >nul
  echo [INFO] Created python\.env from .env.example
)
popd

echo [OK] %PROFILE% setup finished.
echo [NEXT] Edit python\.env and set the required model credentials.
exit /b 0

:require_cmd
where %1 >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Command not found: %1
  exit /b 1
)
exit /b 0

:error
popd 2>nul
echo [ERROR] install.bat %PROFILE% failed.
exit /b 1
