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

echo [3/3] Creating Python venv and installing core dependencies...
pushd python
if not exist ".venv\Scripts\python.exe" (
  %PY_CMD% -m venv .venv
  if errorlevel 1 goto :error
)

call ".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error

call ".venv\Scripts\python.exe" -m pip install "fastapi>=0.136,<1" "uvicorn[standard]>=0.49,<1" "httpx>=0.28,<1" "aiofiles>=25,<26" "numpy>=2.1,<3" "python-multipart>=0.0.32,<1" "python-socketio>=5.16,<6" "sqlalchemy>=2.0.50,<3" "alembic>=1.18,<2" "Pillow>=12,<13" "rapidocr-onnxruntime>=1.2.3,<2"
if errorlevel 1 goto :error

if not exist ".env" (
  copy /y ".env.example" ".env" >nul
  echo [INFO] Created python\.env from .env.example
)
popd

echo [OK] Core setup finished.
echo [NEXT] Edit python\.env and set LLM_API_KEY before using chat/TTS.
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
echo [ERROR] install_core.bat failed.
exit /b 1
