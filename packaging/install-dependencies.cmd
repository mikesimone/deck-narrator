@echo off
rem Installs a minimal LibreOffice if neither PowerPoint nor LibreOffice is here. See install-dependencies.ps1.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-dependencies.ps1"
