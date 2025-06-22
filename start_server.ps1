Write-Host "🚀 Starting JitoX PRO Mini App Local Server..." -ForegroundColor Green
Write-Host ""
Write-Host "Your mini app will be available at: http://localhost:8000" -ForegroundColor Yellow
Write-Host ""
Write-Host "Press Ctrl+C to stop the server" -ForegroundColor Cyan
Write-Host ""

# Change to deploy directory
Set-Location "deploy"

# Start the server
python -m http.server 8000 