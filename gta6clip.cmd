@echo off
cd /d "%~dp0"
@"%USERPROFILE%\.gta6-clipper\venv\Scripts\python.exe" -m gta6clip.run %*
