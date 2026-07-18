@echo off
REM ============================================================
REM BOT.FOREX - Arranque con doble clic (Windows)
REM
REM Abre dos ventanas: backend (API + motor) y dashboard (React).
REM El bot se reanuda solo si estaba activo antes del apagado.
REM
REM Tip: cree un acceso directo a este archivo en la carpeta de
REM inicio de Windows (Win+R -> shell:startup) para que todo
REM arranque automaticamente cuando vuelva la luz y el PC encienda.
REM ============================================================

start "BOT.FOREX backend" cmd /k "cd /d %~dp0..\backend && .venv\Scripts\activate && python -m uvicorn app.main:app --port 8000"
start "BOT.FOREX dashboard" cmd /k "cd /d %~dp0..\frontend && npm run dev"

timeout /t 8 /nobreak >nul
start http://localhost:5173
