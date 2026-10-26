@echo off
rem ATI Terminal - Start per Doppelklick (Windows 10/11)
rem Installiert bei Bedarf "uv" (Python-Paketmanager inkl. Python), richtet alles ein,
rem startet Server + Dashboard und oeffnet den Browser. Fenster offen lassen = Server laeuft.
setlocal
title ATI Terminal
cd /d "%~dp0"

echo.
echo  ===========================================
echo   ATI Terminal - Market Intelligence
echo   Analyse only - es werden keine Orders ausgefuehrt
echo  ===========================================
echo.

rem --- 1) uv finden oder installieren ----------------------------------------
where uv >nul 2>nul
if errorlevel 1 if exist "%USERPROFILE%\.local\bin\uv.exe" set "PATH=%USERPROFILE%\.local\bin;%PATH%"
where uv >nul 2>nul
if errorlevel 1 (
  echo [1/4] uv wird installiert ^(einmalig^) ...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
  set "PATH=%USERPROFILE%\.local\bin;%PATH%"
)
where uv >nul 2>nul
if errorlevel 1 goto :fail_uv
echo [1/4] uv gefunden.

rem --- 2) Alpaca-Keys beim ersten Start abfragen ------------------------------
if not exist "config\alpaca.env" (
  echo.
  echo [2/4] Alpaca-Keys einrichten ^(einmalig^). Leer lassen = DEMO-Modus mit simulierten Daten.
  set /p "AKEY=      API Key ID:     "
  set /p "ASEC=      API Secret Key: "
  call :write_keys
) else (
  echo [2/4] Alpaca-Keys vorhanden ^(config\alpaca.env^).
)

rem --- 3) Abhaengigkeiten ------------------------------------------------------
echo [3/4] Abhaengigkeiten werden geprueft ^(erster Start: einige Minuten^) ...
uv sync --project backend --frozen --no-dev
if errorlevel 1 goto :fail

rem --- 4) Starten --------------------------------------------------------------
if not exist data mkdir data
set "DATABASE_URL=sqlite+aiosqlite:///./data/ati.db"
echo [4/4] Server startet - der Browser oeffnet sich automatisch: http://127.0.0.1:8000
echo       Zum Beenden dieses Fenster schliessen oder Strg+C druecken.
echo.
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "for($i=0;$i -lt 180;$i++){try{Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/health | Out-Null; Start-Process 'http://127.0.0.1:8000'; break}catch{Start-Sleep -Seconds 1}}"
uv run --project backend --frozen --no-dev uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
if errorlevel 1 goto :fail
goto :eof

:write_keys
if not exist config mkdir config
> "config\alpaca.env" echo # Alpaca Market Data Keys (nur lokal, nicht auf GitHub)
>> "config\alpaca.env" echo ALPACA_API_KEY_ID=%AKEY%
>> "config\alpaca.env" echo ALPACA_API_SECRET_KEY=%ASEC%
echo       Gespeichert in config\alpaca.env
goto :eof

:fail_uv
echo.
echo FEHLER: uv konnte nicht installiert werden. Bitte Internetverbindung pruefen
echo oder uv manuell installieren: https://docs.astral.sh/uv/getting-started/installation/
pause
exit /b 1

:fail
echo.
echo FEHLER beim Start - Details siehe oben. Laeuft das Programm schon in einem anderen Fenster
echo ^(Port 8000 belegt^)?
pause
exit /b 1
