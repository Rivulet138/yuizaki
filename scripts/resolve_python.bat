@echo off
set "PY_CMD="

where py >nul 2>nul
if not errorlevel 1 (
  for %%V in (3.13 3.12 3.11) do (
    if not defined PY_CMD (
      py -%%V -c "import sys" >nul 2>nul
      if not errorlevel 1 set "PY_CMD=py -%%V"
    )
  )
)

if not defined PY_CMD (
  where python >nul 2>nul
  if not errorlevel 1 (
    python -c "import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 14) else 1)" >nul 2>nul
    if not errorlevel 1 set "PY_CMD=python"
  )
)

if not defined PY_CMD (
  echo [ERROR] Python 3.11, 3.12, or 3.13 was not found.
  exit /b 1
)
exit /b 0
