@echo off
cd /d "%~dp0"
python launcher.py --browser opera
if errorlevel 1 pause
