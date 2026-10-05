@echo off
rem Runs narrate.py inside this folder's venv. setup.ps1 -AddToPath puts this folder on PATH.
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo deck-narrator: venv missing; run setup.ps1 first 1>&2
    exit /b 1
)
"%~dp0.venv\Scripts\python.exe" "%~dp0narrate.py" %*
