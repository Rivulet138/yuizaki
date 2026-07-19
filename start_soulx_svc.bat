@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "ROOT=%~dp0"
set "SERVICE_DIR=%ROOT%services\soulx-svc"
set "PYTHON_EXE=%ROOT%python\.venv\Scripts\python.exe"
set "MODELS_DIR=%SERVICE_DIR%\models"
set "REFERENCES_DIR=%SERVICE_DIR%\references"
set "CHECK_ONLY=0"
set "REF_AUDIO="

if /I "%~1"=="--help" goto usage
if /I "%~1"=="-h" goto usage
if /I "%~1"=="/?" goto usage
if /I "%~1"=="--check" (
  set "CHECK_ONLY=1"
) else (
  if not "%~1"=="" set "REF_AUDIO=%~1"
)

call :info "Yuizaki SoulX-Singer-SVC one-click launcher"
call :info "Service directory: %SERVICE_DIR%"

if not exist "%SERVICE_DIR%\docker-compose.yml" (
  call :fail "Missing %SERVICE_DIR%\docker-compose.yml"
  exit /b 1
)

if not exist "%PYTHON_EXE%" (
  call :fail "Python venv not found: %PYTHON_EXE%"
  call :info "Run install_full.bat or start.bat --check first."
  exit /b 1
)

docker version >nul 2>nul
if errorlevel 1 (
  call :fail "Docker is not available. Start Docker Desktop and retry."
  exit /b 1
)

docker compose version >nul 2>nul
if errorlevel 1 (
  call :fail "Docker Compose v2 is not available in this Docker installation."
  exit /b 1
)

if "%CHECK_ONLY%"=="1" (
  call :ok "Check passed. Docker, Compose, Python venv, and service files are available."
  exit /b 0
)

if not "%REF_AUDIO%"=="" (
  call :copy_reference "!REF_AUDIO!"
  if errorlevel 1 exit /b 1
)

call :detect_reference
if "%HAS_REF%"=="0" (
  call :info "No reference audio found for speaker_id=0."
  call :info "Opening a file picker for a clean singing reference audio file..."
  call :pick_reference
  if not defined REF_AUDIO (
    set /p "REF_AUDIO=Paste a reference audio path, or press Enter to cancel: "
  )
  if not defined REF_AUDIO (
    call :fail "SoulX needs one reference audio file before startup."
    call :info "Run later with: start_soulx_svc.bat path\to\reference.wav"
    exit /b 1
  )
  call :copy_reference "%REF_AUDIO%"
  if errorlevel 1 exit /b 1
)

set "NEED_MODELS=0"
if not exist "%MODELS_DIR%\SoulX-Singer\model-svc.pt" if not exist "%MODELS_DIR%\SoulX-Singer\model.pt" set "NEED_MODELS=1"
if not exist "%MODELS_DIR%\SoulX-Singer-Preprocess" set "NEED_MODELS=1"

if "%NEED_MODELS%"=="1" (
  call :info "SoulX model files are missing; downloading from Hugging Face..."
  "%PYTHON_EXE%" -m pip show huggingface_hub >nul 2>nul
  if errorlevel 1 (
    call :info "Installing huggingface_hub into the existing Yuizaki venv..."
    "%PYTHON_EXE%" -m pip install huggingface_hub
    if errorlevel 1 (
      call :fail "Failed to install huggingface_hub"
      exit /b 1
    )
  )
  "%PYTHON_EXE%" "%SERVICE_DIR%\download_models.py"
  if errorlevel 1 (
    call :fail "SoulX model download failed"
    exit /b 1
  )
) else (
  call :ok "SoulX model files already exist"
)

call :detect_reference
if "%HAS_REF%"=="0" (
  call :fail "No reference audio found for speaker_id=0."
  call :info "Run: start_soulx_svc.bat path\to\reference.wav"
  call :info "Or place a file at services\soulx-svc\references\0.wav"
  exit /b 1
)

call :info "Starting SoulX-Singer-SVC Docker service on http://127.0.0.1:7861 ..."
docker compose -f "%SERVICE_DIR%\docker-compose.yml" up --build
exit /b %ERRORLEVEL%

:copy_reference
set "SOURCE_REF=%~1"
if not exist "%SOURCE_REF%" (
  call :fail "Reference audio not found: %SOURCE_REF%"
  exit /b 1
)
if not exist "%REFERENCES_DIR%" mkdir "%REFERENCES_DIR%"
for %%A in ("%SOURCE_REF%") do set "REF_EXT=%%~xA"
if /I not "!REF_EXT!"==".wav" if /I not "!REF_EXT!"==".mp3" if /I not "!REF_EXT!"==".flac" if /I not "!REF_EXT!"==".m4a" (
  call :fail "Reference audio must be .wav, .mp3, .flac, or .m4a"
  exit /b 1
)
copy /Y "%SOURCE_REF%" "%REFERENCES_DIR%\0!REF_EXT!" >nul
call :ok "Reference audio copied to services\soulx-svc\references\0!REF_EXT!"
exit /b 0

:pick_reference
for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName System.Windows.Forms; $dlg = New-Object System.Windows.Forms.OpenFileDialog; $dlg.Title = 'Select SoulX reference audio'; $dlg.Filter = 'Audio files (*.wav;*.mp3;*.flac;*.m4a)|*.wav;*.mp3;*.flac;*.m4a|All files (*.*)|*.*'; if ($dlg.ShowDialog() -eq 'OK') { [Console]::WriteLine($dlg.FileName) }"`) do set "REF_AUDIO=%%P"
exit /b 0

:detect_reference
set "HAS_REF=0"
for %%F in (
  "%REFERENCES_DIR%\0.wav"
  "%REFERENCES_DIR%\0.mp3"
  "%REFERENCES_DIR%\0.flac"
  "%REFERENCES_DIR%\0.m4a"
  "%REFERENCES_DIR%\0\prompt.wav"
  "%REFERENCES_DIR%\0\reference.wav"
  "%REFERENCES_DIR%\default.wav"
  "%REFERENCES_DIR%\default.mp3"
) do (
  if exist "%%~F" set "HAS_REF=1"
)
exit /b 0

:usage
echo Usage:
echo   start_soulx_svc.bat --check
echo   start_soulx_svc.bat path\to\reference.wav
echo   start_soulx_svc.bat
echo.
echo First run: double-click the script or pass a clean singing reference audio
echo file. The script checks Docker, downloads SoulX model assets, copies the
echo reference as speaker_id=0, builds the image, and starts the Docker service.
echo Later runs can omit the file.
exit /b 0

:info
echo [INFO]  %~1
exit /b 0

:ok
echo [OK]    %~1
exit /b 0

:fail
echo [ERROR] %~1
exit /b 0
