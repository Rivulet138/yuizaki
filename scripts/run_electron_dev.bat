@echo off
setlocal EnableExtensions EnableDelayedExpansion
for %%I in ("%~dp0..\electron") do set "ELECTRON_ROOT=%%~fI"
pushd "%ELECTRON_ROOT%" >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Failed to enter electron directory: %ELECTRON_ROOT%
  exit /b 1
)

if not defined APP_ENV set "APP_ENV=development"
if not defined ENV set "ENV=development"
if not defined NODE_ENV set "NODE_ENV=development"
if not defined SERVER_HOST set "SERVER_HOST=localhost"
if not defined SERVER_PORT set "SERVER_PORT=8001"
if not defined CONTROL_SERVER_PORT set "CONTROL_SERVER_PORT=38945"
if not defined LOG_LEVEL set "LOG_LEVEL=DEBUG"
if not defined DESKTOP_PET_SKIP_INTERNAL_PYTHON set "DESKTOP_PET_SKIP_INTERNAL_PYTHON=1"
if not defined DESKTOP_PET_BACKEND_URL set "DESKTOP_PET_BACKEND_URL=http://%SERVER_HOST%:%SERVER_PORT%"
if not defined BACKEND_URL set "BACKEND_URL=http://%SERVER_HOST%:%SERVER_PORT%"
if not defined YUIZAKI_ELECTRON_ROOT set "YUIZAKI_ELECTRON_ROOT=%ELECTRON_ROOT%"
set "ELECTRON_RUN_AS_NODE="

if /I "%~1"=="--check" (
  if not exist "package.json" (
    echo [ERROR] Electron package.json missing in: %CD%
    exit /b 1
  )
  if not exist "node_modules\.bin\electron.cmd" (
    echo [ERROR] Electron command missing: %CD%\node_modules\.bin\electron.cmd
    exit /b 1
  )
  echo [OK] Electron dev runner check passed: %CD%
  exit /b 0
)

npm run dev

echo.
echo [INFO] Electron dev process exited. Press any key to close this window.
pause >nul
