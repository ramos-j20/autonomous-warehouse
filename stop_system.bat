@echo off
echo Stopping All Python Processes Instantly...
taskkill /F /IM python.exe /T 2>nul
echo Done.
pause
