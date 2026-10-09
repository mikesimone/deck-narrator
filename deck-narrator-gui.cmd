@echo off
rem Opens the deck-narrator window, using this folder's venv (no console window).
if not exist "%~dp0.venv\Scripts\pythonw.exe" (
    echo deck-narrator-gui: venv missing; run setup.ps1 first 1>&2
    exit /b 1
)
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0gui.py" %*
