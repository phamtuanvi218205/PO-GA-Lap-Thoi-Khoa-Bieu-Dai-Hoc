@echo off
setlocal
title GA-PO - Ung dung xep thoi khoa bieu
pushd "%~dp0"
if errorlevel 1 exit /b 1
set PYTHONUTF8=1
set PYTHONDONTWRITEBYTECODE=1
set "GAPO_LAUNCHER_READY="
set "GAPO_LAUNCHER_EXIT=1"
set "GAPO_LAUNCHER_CHECK="
if "%~1"=="--check" set "GAPO_LAUNCHER_CHECK=1"

if exist ".venv\Scripts\python.exe" call :try_python "%~dp0.venv\Scripts\python.exe"
if defined GAPO_LAUNCHER_READY goto finish
if exist "venv\Scripts\python.exe" call :try_python "%~dp0venv\Scripts\python.exe"
if defined GAPO_LAUNCHER_READY goto finish
call :try_python py -3
if defined GAPO_LAUNCHER_READY goto finish
call :try_python python
if defined GAPO_LAUNCHER_READY goto finish

echo.
echo Khong tim thay Python 3.11+ co du thu vien cua du an.
echo Cai moi truong theo README, roi bam lai file nay.
echo Lenh cai dat mot lan, tai thu muc du an: python -m pip install -r requirements.txt
goto finish

:try_python
%* -B "%~dp0Script\start_demo.py" --check >nul 2>&1
if errorlevel 1 exit /b 0
set "GAPO_LAUNCHER_READY=1"
if defined GAPO_LAUNCHER_CHECK (
    echo Moi truong Python san sang. Khong khoi chay server.
    set "GAPO_LAUNCHER_EXIT=0"
    exit /b 0
)
%* -B "%~dp0Script\start_demo.py"
set "GAPO_LAUNCHER_EXIT=%errorlevel%"
exit /b 0

:finish
if not "%GAPO_LAUNCHER_EXIT%"=="0" pause
popd
exit /b %GAPO_LAUNCHER_EXIT%
