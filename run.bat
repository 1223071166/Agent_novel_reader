@echo off
cd /d "%~dp0"
title AgentReader Development Server

echo Starting frontend and backend...
echo Frontend: http://localhost:5173
echo Backend:  http://127.0.0.1:8000
echo.

start "" /b cmd /c "npm --prefix frontend run dev"
start "" /b cmd /c "uvicorn backend.main:app --reload"

echo Both services are running in this window.
echo Close this window to stop them.
echo.

pause >nul
