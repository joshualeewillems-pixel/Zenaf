# Temporary launcher: start API + frontend and open the cockpit in the browser.
# Run from repo root: .\open-cockpit.ps1

$root = $PSScriptRoot
if (-not $root) { $root = Get-Location }

# Start API in a new window
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root'; python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8010"

# Start frontend in a new window
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\frontend'; npm run dev"

# Give servers a moment to bind
Start-Sleep -Seconds 4

# Open app and API docs in default browser
Start-Process "http://127.0.0.1:5173"
Start-Process "http://127.0.0.1:8010/docs"

Write-Host "Cockpit: API and frontend started in separate windows."
Write-Host "Browser opened: app (http://127.0.0.1:5173) and API docs (http://127.0.0.1:8010/docs)"
