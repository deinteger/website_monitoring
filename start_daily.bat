@echo off
cd /d "%~dp0"
python daily_batch.py %*
exit /b %ERRORLEVEL%
