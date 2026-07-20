@echo off
REM ============================================================
REM BOT.FOREX - Instalar el auto-arranque (ejecutar UNA sola vez)
REM
REM Crea un lanzador en la carpeta de Inicio de Windows para que,
REM cada vez que la PC encienda e inicie sesion (por ejemplo tras
REM un corte de luz), el bot completo arranque solo: backend,
REM dashboard y navegador. Sin escribir ningun comando.
REM ============================================================

set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"

> "%STARTUP%\BOTFOREX_autoarranque.bat" echo @echo off
>> "%STARTUP%\BOTFOREX_autoarranque.bat" echo start "" "%~dp0start_windows.bat"

echo ============================================================
echo LISTO: BOT.FOREX arrancara automaticamente cada vez que
echo encienda la PC e inicie sesion en Windows.
echo.
echo Si el bot estaba activo cuando se fue la luz, tambien se
echo reanudara solo (siempre que el terminal MT5 este configurado
echo para abrirse con Windows o el bot pueda relanzarlo).
echo.
echo Para desactivarlo: doble clic en quitar_autoarranque.bat
echo ============================================================
pause
