
@echo off
REM Double-click to start API + frontend, then open the app and API docs in your browser.
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "%~dp0open-cockpit.ps1"
