@echo off
setlocal EnableExtensions

for %%I in ("%~dp0..") do set "PROJECT_ROOT=%%~fI"
set "LAUNCHER_SOURCE=%PROJECT_ROOT%\tools\yuizaki-launcher\main.go"
set "LAUNCHER_EXE=%PROJECT_ROOT%\YuizakiLauncher.exe"

if not exist "%LAUNCHER_SOURCE%" (
  echo [ERROR] Launcher source missing: %LAUNCHER_SOURCE%
  exit /b 1
)

where go >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Go toolchain is not available in PATH.
  exit /b 1
)

pushd "%PROJECT_ROOT%" >nul
go build -trimpath -ldflags "-s -w" -o "%LAUNCHER_EXE%" "%LAUNCHER_SOURCE%"
set "BUILD_EXIT_CODE=%ERRORLEVEL%"
popd >nul

if not "%BUILD_EXIT_CODE%"=="0" (
  echo [ERROR] Failed to build YuizakiLauncher.exe
  exit /b %BUILD_EXIT_CODE%
)

echo [OK] Built %LAUNCHER_EXE%
exit /b 0
