@echo off
REM ============================================================
REM BOT.FOREX - Arranque con doble clic (Windows)
REM
REM Abre dos ventanas: backend (API + motor) y dashboard (React),
REM y luego abre el navegador. No requiere escribir ningun comando.
REM
REM Usa el python.exe del entorno .venv DIRECTAMENTE (sin activate),
REM asi funciona igual desde cmd, PowerShell o doble clic.
REM ============================================================

if not exist "%~dp0..\backend\.venv\Scripts\python.exe" (
    echo ============================================================
    echo ERROR: no se encontro el entorno del backend ^(.venv^).
    echo Abra la GUIA_RAPIDA.txt en la carpeta del proyecto y siga
    echo la seccion "PRIMERA INSTALACION".
    echo ============================================================
    pause
    exit /b 1
)

start "BOT.FOREX backend" /d "%~dp0..\backend" cmd /k .venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
start "BOT.FOREX dashboard" /d "%~dp0..\frontend" cmd /k npm run dev

timeout /t 10 /nobreak >nul
start http://localhost:5173
