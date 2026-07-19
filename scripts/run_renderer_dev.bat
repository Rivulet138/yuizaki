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

if /I "%~1"=="--check" (
  if not exist "package.json" (
    echo [ERROR] Renderer package.json missing in: %CD%
    exit /b 1
  )
  if not exist "node_modules\.bin\vite.cmd" (
    echo [ERROR] Vite command missing: %CD%\node_modules\.bin\vite.cmd
    exit /b 1
  )
  echo [OK] Renderer runner check passed: %CD%
  exit /b 0
)

call npm run dev:renderer
set "RENDERER_EXIT_CODE=%ERRORLEVEL%"

echo.
if "%YUIZAKI_SUPERVISOR%"=="1" exit /b %RENDERER_EXIT_CODE%
echo [INFO] Renderer dev server exited. Press any key to close this window.
pause >nul
