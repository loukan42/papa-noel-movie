@echo off
rem Vidéo du Père Noël, voix gratuite. Usage : Generer-Pere-Noel.cmd [Prénom] [prononciation]
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set "PRENOM=%~1"
set "PRON=%~2"
if "%PRENOM%"=="" set /p "PRENOM=Prénom de l'enfant : "
if "%PRENOM%"=="" exit /b 1
if "%PRON%"=="" (
  ".venv\Scripts\python.exe" -u pere_noel.py generer "%PRENOM%"
) else (
  ".venv\Scripts\python.exe" -u pere_noel.py generer "%PRENOM%" --prononciation "%PRON%"
)
if errorlevel 1 (
  echo.
  echo La génération a échoué. Le détail est au-dessus.
  pause
  exit /b 1
)
start "" explorer "%~dp0exports"
pause
