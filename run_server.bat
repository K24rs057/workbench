@echo off
cd /d "%~dp0"
python app.py >> run_log.txt 2>&1
