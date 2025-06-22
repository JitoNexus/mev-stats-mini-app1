@echo off
echo Starting JitoX PRO Mini App Local Server...
echo.
echo Your mini app will be available at: http://localhost:8000
echo.
echo Press Ctrl+C to stop the server
echo.
cd deploy
python -m http.server 8000
pause 