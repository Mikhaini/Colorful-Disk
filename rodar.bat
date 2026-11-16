@echo off
cd /d "%~dp0"
python -m pip install -r requirements.txt
echo.
echo Abra http://localhost:5000 no navegador. Feche esta janela para parar o site.
python app.py
pause
