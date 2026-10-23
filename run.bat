@echo off
rem Traffiqui Vision - instala (la primera vez) y arranca el servidor.
rem Uso:  run.bat                     usa la camara configurada
rem       run.bat --source demo.mp4   modo demo con un video en bucle
rem       run.bat --setup             solo instala, no arranca
setlocal EnableExtensions
cd /d "%~dp0"
title Traffiqui Vision

rem ---- 1. Buscar Python 3.11 (o 3.12) ----------------------------------------
set "PY="
for %%V in (3.11 3.12) do (
  if not defined PY (
    py -%%V -c "import sys" >nul 2>nul && set "PY=py -%%V"
  )
)
if not defined PY (
  for %%P in ("%LOCALAPPDATA%\Programs\Python\Python311\python.exe" "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" "%ProgramFiles%\Python311\python.exe" "%ProgramFiles%\Python312\python.exe") do (
    if not defined PY if exist %%P set "PY="%%~P""
  )
)
if not defined PY (
  python -c "import sys; sys.exit(0 if sys.version_info[:2] in ((3,11),(3,12)) else 1)" >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo.
  echo [ERROR] No se encontro Python 3.11 ni 3.12.
  echo         Instalalo desde https://www.python.org/downloads/ marcando "Add python.exe to PATH",
  echo         o con:  winget install Python.Python.3.11
  echo.
  pause
  exit /b 1
)

rem ---- 2. Entorno virtual --------------------------------------------------
rem torch trae archivos con rutas de ~125 caracteres: con la carpeta muy anidada
rem se supera el limite de 260 de Windows y la instalacion falla.
set "PLEN=0"
set "LONGOK="
if not exist ".venv\requirements.installed" (
  reg query "HKLM\SYSTEM\CurrentControlSet\Control\FileSystem" /v LongPathsEnabled 2>nul | find "0x1" >nul && set "LONGOK=1"
  for /f %%L in ('powershell -NoProfile -Command "(Get-Location).Path.Length"') do set "PLEN=%%L"
)
if not exist ".venv\requirements.installed" if not defined LONGOK if %PLEN% GTR 110 (
  echo.
  echo [ERROR] La ruta de esta carpeta es muy larga ^(%PLEN% caracteres^):
  echo         %CD%
  echo         Windows limita las rutas a 260 caracteres y la instalacion de PyTorch fallaria.
  echo         Mueve la carpeta a una ruta corta, por ejemplo C:\traffiqui-vision, y vuelve a ejecutar run.bat.
  echo         ^(Alternativa: activar "rutas largas" de Windows con permisos de administrador.^)
  echo.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo Creando entorno virtual .venv ...
  %PY% -m venv .venv || goto :fail
)
set "VPY=.venv\Scripts\python.exe"

rem ---- 3. Dependencias (solo si requirements.txt cambio; asi arranca sin internet) ----
fc /b requirements.txt ".venv\requirements.installed" >nul 2>nul
if errorlevel 1 (
  echo Instalando dependencias. La primera vez descarga ~200 MB y tarda unos minutos...
  "%VPY%" -m pip install --disable-pip-version-check -q --upgrade pip
  "%VPY%" -m pip install --disable-pip-version-check -r requirements.txt || goto :fail
  copy /y requirements.txt ".venv\requirements.installed" >nul
)

rem ---- 4. Modelo de deteccion: viene en models\ (detector-personas.onnx) ---
if not exist "models\detector-personas.onnx" (
  echo [ERROR] Falta models\detector-personas.onnx. Vuelve a descargar el proyecto completo.
  goto :fail
)

if /i "%~1"=="--setup" (
  echo Instalacion lista. Ejecuta run.bat para arrancar.
  exit /b 0
)

rem ---- 5. Arrancar y abrir el navegador cuando responda ----------------------
rem      Ctrl+C para cerrar: libera la camara y guarda lo pendiente en SQLite.
echo.
"%VPY%" -m app.main --open %*
exit /b %errorlevel%

:fail
echo.
echo [ERROR] La instalacion fallo. Revisa tu conexion a internet (solo se necesita la primera vez)
echo         y vuelve a ejecutar run.bat. Si persiste, borra la carpeta .venv y reintenta.
pause
exit /b 1
