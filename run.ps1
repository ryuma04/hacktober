# One-command start for DepExit on Windows: AI service (:8001) + Go API (:8080) [+ frontend (:3000) if present].
# Usage:  powershell -ExecutionPolicy Bypass -File run.ps1
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

if (-not (Test-Path "$root\.env")) { Copy-Item "$root\.env.example" "$root\.env"; Write-Host "Created .env - add GEMINI_API_KEYS" }

# AI service
if (-not (Test-Path "$root\ai\.venv")) {
    py -3.12 -m venv "$root\ai\.venv"
    & "$root\ai\.venv\Scripts\python.exe" -m pip install -q -r "$root\ai\requirements.txt"
}
Start-Process -FilePath "$root\ai\.venv\Scripts\python.exe" -ArgumentList "-m","uvicorn","app.main:app","--port","8001" `
    -WorkingDirectory "$root\ai" -WindowStyle Minimized
Write-Host "AI service  -> http://localhost:8001/v1/health"

# Go API
$goExe = if (Get-Command go -ErrorAction SilentlyContinue) { "go" } elseif (Test-Path "$env:USERPROFILE\go\bin\go.exe") { "$env:USERPROFILE\go\bin\go.exe" } else { "go" }
Push-Location "$root\backend"; & $goExe build -o bin\depexit.exe .; Pop-Location
Start-Process -FilePath "$root\backend\bin\depexit.exe" -WorkingDirectory "$root" -WindowStyle Minimized
Write-Host "Go API      -> http://localhost:8080/api/health"

# Frontend (if the UI lane has pushed it)
if (Test-Path "$root\frontend\package.json") {
    Push-Location "$root\frontend"
    if (-not (Test-Path "node_modules")) { npm install }
    Start-Process -FilePath "npm.cmd" -ArgumentList "run","dev" -WorkingDirectory "$root\frontend" -WindowStyle Minimized
    Pop-Location
    Write-Host "Frontend    -> http://localhost:3000"
}
