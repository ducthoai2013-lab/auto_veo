@echo off
rem Chay Gateway Auto_veo3 (cua so console). Tu khoi dong cung Windows: xem docs\TRIEN-KHAI.md muc C.
cd /d "%~dp0"
:loop
glabs-gateway.exe serve --host 127.0.0.1 --port 8080
echo Gateway dung (ma %errorlevel%). Chay lai sau 5 giay... (dong cua so de thoat)
timeout /t 5 /nobreak >nul
goto loop
