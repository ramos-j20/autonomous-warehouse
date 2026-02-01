@echo off
echo Starting Warehouse System (Group G2021231020)...

echo Starting Gateway...
start "Gateway" python warehouse_gateway.py G2021231020
timeout /t 2

echo Starting Fleet Coordinator...
start "Coordinator" python fleet_coordinator.py G2021231020
timeout /t 2

echo Starting System Monitor...
start "Monitor" python system_monitor.py G2021231020
timeout /t 2

echo Starting MQTT Debugger...
start "Debugger" python mqtt_debugger.py G2021231020
timeout /t 2

echo Starting AMR Robots...
start "AMR-1" python amr_robot.py G2021231020 AMR-1
timeout /t 2
start "AMR-2" python amr_robot.py G2021231020 AMR-2
timeout /t 2
start "AMR-3" python amr_robot.py G2021231020 AMR-3
timeout /t 2
start "AMR-4" python amr_robot.py G2021231020 AMR-4
timeout /t 2

echo Starting Shelves (Storage A)...
start "Shelf S1" python shelves.py G2021231020 storage-a S1 5
timeout /t 2
start "Shelf S2" python shelves.py G2021231020 storage-a S2 5
timeout /t 2
start "Shelf S3" python shelves.py G2021231020 storage-a S3 5
timeout /t 2
start "Shelf S4" python shelves.py G2021231020 storage-a S4 5
timeout /t 2
start "Shelf S5" python shelves.py G2021231020 storage-a S5 5
timeout /t 2

echo Starting Shelves (Storage B)...
start "Shelf S6" python shelves.py G2021231020 storage-b S6 5
timeout /t 2
start "Shelf S7" python shelves.py G2021231020 storage-b S7 5
timeout /t 2
start "Shelf S8" python shelves.py G2021231020 storage-b S8 5
timeout /t 2
start "Shelf S9" python shelves.py G2021231020 storage-b S9 5
timeout /t 2
start "Shelf S10" python shelves.py G2021231020 storage-b S10 5
timeout /t 2

echo System Started.
pause
