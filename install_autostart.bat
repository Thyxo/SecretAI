@echo off
rem Laver en genvej i Windows' Startup-mappe, saa SecretAI starter med computeren.
set "VBS=%~dp0start_hidden.vbs"
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Startup')+'\SecretAI.lnk'); $s.TargetPath='wscript.exe'; $s.Arguments='\"%VBS%\"'; $s.WorkingDirectory='%~dp0'; $s.Save()"
echo SecretAI starter nu automatisk ved login. Fjern genvejen "SecretAI" i shell:startup for at slaa det fra.
pause
