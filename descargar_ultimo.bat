@echo off
cd /d "C:\Users\pc\Desktop\github\geca-radar"

echo 1 | python scripts\descarga_github.py

exit /b %ERRORLEVEL%