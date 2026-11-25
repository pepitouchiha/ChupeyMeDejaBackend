@echo off
setlocal EnableDelayedExpansion
rem Arranca el backend de Chupe y Me Deja en este PC (solo desarrollo local;
rem en produccion el backend corre en Render). Vive en la raiz de backend\ (al lado de app\);
rem todo se resuelve desde la ubicacion de este .bat, asi funciona aunque el acceso
rem directo de la carpeta de inicio de Windows tenga otro "Iniciar en".

set "BACKEND=%~dp0"
set "BACKEND=%BACKEND:~0,-1%"
set "PY=%BACKEND%\.venv\Scripts\python.exe"
set "LOGDIR=%BACKEND%\logs"
set "LOG=%LOGDIR%\backend.log"
set "PORT=8000"
set "MAX_REINTENTOS=5"
set "PYTHONUTF8=1"

title Chupe y Me Deja - Backend
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

if not exist "%BACKEND%\app\main.py" (
    echo [ERROR] No se encontro "%BACKEND%\app\main.py".
    echo         Este .bat debe estar en la carpeta backend\, al lado de app\
    goto :fallo
)
cd /d "%BACKEND%"

if not exist "%BACKEND%\.env" (
    echo [ERROR] Falta "%BACKEND%\.env". Copia .env.example a .env y configuralo.
    goto :fallo
)

if not exist "%PY%" (
    echo [ERROR] No existe el entorno virtual: "%PY%"
    echo         Crealo con:  cd /d "%BACKEND%" ^&^& python -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt
    goto :fallo
)

rem Un .venv copiado desde otro PC, o creado con un Python que luego se
rem desinstalo/actualizo, queda roto: python.exe existe pero no arranca.
"%PY%" -c "import fastapi, uvicorn, sqlalchemy, dotenv, jwt, bcrypt, psycopg" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] El entorno virtual esta roto o le faltan dependencias.
    echo         Recrealo:
    echo           cd /d "%BACKEND%"
    echo           rmdir /s /q .venv
    echo           python -m venv .venv
    echo           .venv\Scripts\pip install -r requirements.txt
    "%PY%" -c "import fastapi, uvicorn, sqlalchemy, dotenv, jwt, bcrypt, psycopg"
    goto :fallo
)

netstat -ano | findstr /r /c:"127.0.0.1:%PORT% .*LISTENING" /c:"0.0.0.0:%PORT% .*LISTENING" >nul
if not errorlevel 1 (
    echo [AVISO] Ya hay algo escuchando en el puerto %PORT%. Probablemente el backend
    echo         ya esta corriendo en otra ventana. Revisa http://127.0.0.1:%PORT%/health
    goto :fallo
)

set /a INTENTO=0
:arrancar
set /a INTENTO+=1
echo [%date% %time%] Iniciando backend (intento !INTENTO!)... >> "%LOG%"
echo Backend corriendo en http://127.0.0.1:%PORT%  -  log: "%LOG%"
echo No cierres esta ventana.
"%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port %PORT% >> "%LOG%" 2>&1
set "CODIGO=!errorlevel!"
echo [%date% %time%] El backend se detuvo (codigo !CODIGO!). >> "%LOG%"
echo [ERROR] El backend se detuvo (codigo !CODIGO!). Ultimas lineas del log:
powershell -NoProfile -Command "Get-Content -LiteralPath '%LOG%' -Tail 25"
if !INTENTO! lss %MAX_REINTENTOS% (
    echo Reintentando en 5 segundos...
    timeout /t 5 /nobreak >nul
    goto :arrancar
)
echo [ERROR] Fallo %MAX_REINTENTOS% veces seguidas. Revisa el log completo: "%LOG%"

:fallo
echo.
pause
exit /b 1
