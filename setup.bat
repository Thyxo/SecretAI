@echo off
cd /d "%~dp0"
echo Installerer afhaengigheder...
python -m pip install -r requirements.txt
where pythonw >nul 2>nul || (echo FEJL: pythonw findes ikke i PATH. Installer Python fra python.org og saet kryds ved "Add to PATH". & pause & exit /b 1)
echo.
echo Faerdig. Dobbeltklik paa start_hidden.vbs for at starte SecretAI.
echo Kun foerste gang: Chrome aabner, og du logger ind paa DeepSeek.
pause
