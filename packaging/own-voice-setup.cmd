@echo off
rem Sets up "your own voice" (Chatterbox) for this Windows user: deck-narrator --install-own-voice.
rem The installer's finish page offers to run this; Settings > Set up in the app does the same.
title Deck Narrator: setting up your own voice
"%~dp0deck-narrator.exe" --install-own-voice
echo.
if errorlevel 1 (echo Setup stopped; the lines above say why. Running it again picks up where it stopped.) else (echo Done. Open Deck Narrator, then Settings ^> Add a voice.)
pause
