@echo off
REM Elimina el auto-arranque de BOT.FOREX creado por
REM instalar_autoarranque.bat. La aplicacion no se toca.

set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"

if exist "%STARTUP%\BOTFOREX_autoarranque.bat" (
    del "%STARTUP%\BOTFOREX_autoarranque.bat"
    echo Auto-arranque desactivado. Puede volver a activarlo con
    echo instalar_autoarranque.bat cuando quiera.
) else (
    echo El auto-arranque no estaba instalado.
)
pause
