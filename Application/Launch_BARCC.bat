@echo off
REM Launch BARCC as its own Windows app (correct taskbar icon).
REM Prefer this over running barcc.py from a Jupyter notebook cell.
cd /d "%~dp0"

REM Prefer pythonw (no console) then python, then py launcher
where pythonw >nul 2>&1
if %ERRORLEVEL%==0 (
  start "" pythonw "%~dp0barcc.py"
  exit /b 0
)
where python >nul 2>&1
if %ERRORLEVEL%==0 (
  start "" python "%~dp0barcc.py"
  exit /b 0
)
where py >nul 2>&1
if %ERRORLEVEL%==0 (
  start "" py -3 "%~dp0barcc.py"
  exit /b 0
)

echo Could not find pythonw/python/py on PATH.
echo Install Python or launch from Anaconda Prompt:
echo   cd /d "%~dp0"
echo   python barcc.py
pause
