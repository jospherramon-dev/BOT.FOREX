@echo off
REM Revierte activar_autologin.bat: Windows vuelve a pedir el
REM clic/inicio de sesion normal al encender.
REM Ejecutar como administrador (clic derecho -> "Ejecutar
REM como administrador").

net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Necesita ejecutar esto como administrador:
    echo clic derecho sobre este archivo -^> "Ejecutar como administrador".
    pause
    exit /b 1
)

set "RUTA=HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"

reg add "%RUTA%" /v AutoAdminLogon /t REG_SZ /d 0 /f >nul
reg delete "%RUTA%" /v DefaultPassword /f >nul 2>&1

echo Inicio de sesion automatico desactivado. Windows volvera a
echo pedir el inicio de sesion normal al encender.
pause
