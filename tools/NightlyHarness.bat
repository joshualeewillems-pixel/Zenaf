@echo off
cd /d "%~dp0\.."
python tools\nightly_harness_gui.py
if errorlevel 1 pause
