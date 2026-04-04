@echo off
cd /d "%~dp0"

echo Starting AI File Steward...

start http://localhost:8501

py -m streamlit run app.py
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "cmd /c cd /d ""C:\Users\philc\OneDrive\Desktop\file_steward"" && py -m streamlit run app.py", 0