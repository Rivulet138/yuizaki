@echo off
setlocal EnableExtensions
cd /d "%~dp0"

call :require_cmd node || exit /b 1
call :require_cmd npm || exit /b 1
node -e "const [major, minor] = process.versions.node.split('.').map(Number); process.exit(major > 22 || (major === 22 && minor >= 13) ? 0 : 1)" >nul 2>nul
if errorlevel 1 (
  for /f %%V in ('node -p "process.versions.node" 2^>nul') do set "NODE_VERSION=%%V"
  echo [ERROR] Node.js 22.13+ is required. Current version: %NODE_VERSION%.
  exit /b 1
)
call :resolve_python || exit /b 1

echo [1/3] Installing Electron dependencies...
pushd electron
call npm install
if errorlevel 1 goto :error
popd

echo [2/3] Installing node-mcp dependencies...
pushd node-mcp
call npm install
if errorlevel 1 goto :error
popd

echo [3/3] Creating Python venv and installing default runtime requirements...
pushd python
if not exist ".venv\Scripts\python.exe" (
  %PY_CMD% -m venv .venv
  if errorlevel 1 goto :error
)

call ".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error

call ".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error

if not exist ".env" (
  copy /y ".env.example" ".env" >nul
  echo [INFO] Created python\.env from .env.example
)
popd

echo [OK] Default setup finished.
echo [NEXT] Edit python\.env and set LLM_API_KEY. Optional ASR/SVC model backends are installed separately.
exit /b 0

:require_cmd
where %1 >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Command not found: %1
  exit /b 1
)
exit /b 0

:resolve_python
set "PY_CMD="
where python >nul 2>nul && set "PY_CMD=python"
if not defined PY_CMD (
  where py >nul 2>nul && set "PY_CMD=py -3"
)
if not defined PY_CMD (
  echo [ERROR] Python not found in PATH.
  exit /b 1
)
exit /b 0

:error
popd 2>nul
echo [ERROR] install_full.bat failed.
exit /b 1
