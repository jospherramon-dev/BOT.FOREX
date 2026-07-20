@echo off
REM ============================================================
REM BOT.FOREX - Activar inicio de sesion automatico de Windows
REM
REM Hace que Windows entre DIRECTO al escritorio al encender,
REM sin detenerse en la pantalla de bloqueo ni pedir un clic.
REM Es el paso que falta para que, tras un corte de luz, el bot
REM arranque completamente solo sin que nadie toque la PC.
REM
REM IMPORTANTE: debe ejecutar este archivo como administrador
REM (clic derecho sobre el archivo -> "Ejecutar como
REM administrador"). Con doble clic normal no funciona.
REM ============================================================

net session >nul 2>&1
if %errorLevel% neq 0 (
    echo ============================================================
    echo Este script necesita permisos de administrador.
    echo Cierre esta ventana. Luego, en el Explorador de archivos,
    echo haga clic DERECHO sobre "activar_autologin.bat" y elija
    echo "Ejecutar como administrador".
    echo ============================================================
    pause
    exit /b 1
)

set "RUTA=HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"

echo Este es el nombre de usuario que vio en "Cuentas de usuario"
echo ^(ej. User^).
set /p USUARIO="Escriba el nombre de usuario de Windows: "

reg add "%RUTA%" /v AutoAdminLogon /t REG_SZ /d 1 /f >nul
reg add "%RUTA%" /v DefaultUserName /t REG_SZ /d "%USUARIO%" /f >nul
reg add "%RUTA%" /v DefaultPassword /t REG_SZ /d "" /f >nul

echo.
echo ============================================================
echo LISTO. Reinicie la PC para probarlo: deberia encender e ir
echo directo al escritorio, sin pantalla de bloqueo ni clics.
echo.
echo Para revertir esto: clic derecho -^> Ejecutar como
echo administrador sobre desactivar_autologin.bat
echo ============================================================
pause
