@echo off
setlocal EnableExtensions

for %%I in ("%~dp0..") do set "PROJECT_ROOT=%%~fI"
set "ROOT_START=%PROJECT_ROOT%\start.bat"

if not exist "%ROOT_START%" (
  echo [ERROR] Yuizaki root startup script not found: %ROOT_START%
  exit /b 1
)

call "%ROOT_START%" %*
set "START_EXIT_CODE=%ERRORLEVEL%"
exit /b %START_EXIT_CODE%
