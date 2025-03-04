@echo off
cd /d "%~dp0"  REM Chuyển đến thư mục chứa scri
Cheat_V3\Scripts\activate.bat || exit /b 1
pythonw LMS_bypass.pyw
