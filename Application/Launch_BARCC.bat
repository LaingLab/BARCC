@echo off
REM Launch BARCC on Python 3.14 (conda env barcc314).
REM Prefer this over running barcc.py from a Jupyter notebook cell.
cd /d "%~dp0"

set "BARCC_PY314=C:\Users\blain\anaconda3\envs\barcc314\pythonw.exe"
set "BARCC_PY314_C=C:\Users\blain\anaconda3\envs\barcc314\python.exe"
set "BARCC_PY312=C:\Users\blain\anaconda3\envs\barcc\pythonw.exe"

REM 1) Preferred: dedicated Python 3.14 env (barcc314)
if exist "%BARCC_PY314%" (
  start "" "%BARCC_PY314%" "%~dp0barcc.py"
  exit /b 0
)
if exist "%BARCC_PY314_C%" (
  start "" "%BARCC_PY314_C%" "%~dp0barcc.py"
  exit /b 0
)

REM 2) Legacy barcc env (Python 3.12) if 3.14 env missing
if exist "%BARCC_PY312%" (
  echo WARNING: barcc314 (Python 3.14) not found; using barcc (3.12).
  start "" "%BARCC_PY312%" "%~dp0barcc.py"
  exit /b 0
)

REM 3) py launcher — request 3.14 first
where py >nul 2>&1
if %ERRORLEVEL%==0 (
  py -3.14 -c "import sys" >nul 2>&1
  if %ERRORLEVEL%==0 (
    start "" py -3.14 "%~dp0barcc.py"
    exit /b 0
  )
  start "" py -3 "%~dp0barcc.py"
  exit /b 0
)

REM 4) PATH fallbacks
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

echo Could not find a Python interpreter for BARCC.
echo.
echo Expected: C:\Users\blain\anaconda3\envs\barcc314\python.exe
echo Create it with:
echo   conda create -n barcc314 python=3.14 pip -y
echo   conda activate barcc314
echo   pip install -r ..\requirements.txt xlsxwriter
echo.
pause
