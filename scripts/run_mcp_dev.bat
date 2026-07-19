@echo off
setlocal EnableExtensions EnableDelayedExpansion
for %%I in ("%~dp0..\node-mcp") do set "NODE_MCP_ROOT=%%~fI"
pushd "%NODE_MCP_ROOT%" >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Failed to enter node-mcp directory: %NODE_MCP_ROOT%
  exit /b 1
)

set "NODE_ENV=development"

if /I "%~1"=="--check" (
  if not exist "server.mjs" (
    echo [ERROR] MCP server missing: %CD%\server.mjs
    exit /b 1
  )
  if not exist "node_modules" (
    echo [ERROR] MCP node_modules missing: %CD%\node_modules
    exit /b 1
  )
  echo [OK] MCP runner check passed: %CD%
  exit /b 0
)

npm start
set "MCP_EXIT_CODE=%ERRORLEVEL%"

echo.
if "%YUIZAKI_SUPERVISOR%"=="1" exit /b %MCP_EXIT_CODE%
echo [INFO] MCP process exited. Press any key to close this window.
pause >nul
