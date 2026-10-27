@echo off
cd /d "%~dp0"
if exist "dist\MemuMusic.exe" (
  start "" "dist\MemuMusic.exe"
  exit /b
)
if not exist ".venv\Scripts\pythonw.exe" (
  echo Run build.ps1 first, or install Python dependencies into .venv.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m memumusic
