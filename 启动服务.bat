@echo off
cd /d "%~dp0"
echo [XueXiaoZhu] starting server at http://127.0.0.1:8000
"D:\ccd\ccd\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
