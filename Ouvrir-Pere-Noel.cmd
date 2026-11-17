@echo off
rem Page web : saisir un prénom, suivre le calcul, revoir les vidéos.
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
start "" "http://127.0.0.1:5195"
echo Page : http://127.0.0.1:5195  (laisser cette fenêtre ouverte, Ctrl+C pour arrêter)
".venv\Scripts\python.exe" -u serveur.py
pause
