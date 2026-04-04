@echo off
cd /d "%~dp0"

echo Starting AI File Steward...

py -m streamlit run app.py

pause