@echo off
REM Escucha 24/7 de la alta frecuencia en Hyperliquid. Doble clic para empezar; cerrar la ventana para parar.
chcp 65001 >nul
cd /d "%~dp0.."
title Escucha alta frecuencia - Hyperliquid

where python >nul 2>nul
if errorlevel 1 (
  echo No encuentro Python. Instalalo desde https://www.python.org/downloads/ marcando "Add python.exe to PATH".
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Primera vez: preparando el entorno, tarda un minuto...
  python -m venv .venv
  ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
  ".venv\Scripts\python.exe" -m pip install --quiet -r requirements-escucha.txt
)

REM Tema de ntfy para los avisos (el mismo del monitor)
set NTFY_TOPIC=juan-ruta-d89ef32a94

:loop
".venv\Scripts\python.exe" -m copytrading.escucha
echo La escucha se detuvo. Reiniciando en 30 segundos (cierra la ventana para salir)...
timeout /t 30 >nul
goto loop
