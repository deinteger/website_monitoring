@echo off
cd /d "%~dp0"
start "NIHHS Dashboard Server" /b python -m src.dashboard
timeout /t 1 /nobreak >nul
start "NIHHS Dashboard" http://127.0.0.1:18765/
