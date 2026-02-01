@echo off
echo Installing amqtt...
pip install amqtt
if %ERRORLEVEL% NEQ 0 (
    echo Failed to install amqtt.
    pause
    exit /b %ERRORLEVEL%
)

echo Starting Local MQTT Broker...
echo Press Ctrl+C to stop.
python local_broker.py
pause
