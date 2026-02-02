# Warehouse IIoT System

This project implements a simulated Industrial IoT (IIoT) system for an autonomous warehouse. It includes Autonomous Mobile Robots (AMRs), Smart Shelves, a central Gateway, a Fleet Coordinator, and a System Monitor.

## Components

### 1. AMR Robot Simulator (`amr_robot.py`)
Simulates an autonomous robot with:
- **State Machine**: IDLE, MOVING, PICKING, DROPPING, CHARGING.
- **Battery Logic**: Decays with activity, requires charging.
- **MQTT**: Publishes status and accepts binary commands.
- **Failures**: Random stalling events.

### 2. Smart Shelf Simulator (`shelves.py`)
Simulates a static shelf sensor with:
- **Stock Tracking**: Decreases over time, auto-refills.
- **Zone Logic**: `storage-a` (units), `storage-b` (kg).
- **MQTT**: Publishes stock levels.

### 3. Warehouse Gateway (`warehouse_gateway.py`)
The central bridge that:
- **Normalizes**: Converts all stock units to kg.
- **Persists**: Writes data to InfluxDB Cloud (`robot_status`, `shelf_status`, `system_alerts`, `robot_commands`).
- **UDP Server**: Listens on Port 9090 for overrides (e.g., FORCE_CHARGE).
- **Command Encoding**: Converts JSON dispatch commands to binary for robots.

### 4. Fleet Coordinator (`fleet_coordinator.py`)
The central brain that:
- **UDP Server**: Listens on Port 9091 for client orders.
- **Task Matching**: Assigns orders to IDLE robots and Shelves with stock.
- **Dispatch**: Sends `EXECUTE_TASK` commands via MQTT.

### 5. System Monitor (`system_monitor.py`)
Watchdog that:
- **Detects Stalls**: Robot MOVING but location unchanged > 30s.
- **Detects Low Battery**: Battery < 15% and not charging.
- **Action**: Sends UDP overrides to Gateway (Port 9090).

### 6. Client Order Injector (`client_order_injector.py`)
Interactive CLI tool to send orders to the Fleet Coordinator.

## Usage

### 1. Start the System
Open separate terminal windows for each component and run the following commands in order:

**1. Gateway (Central Bridge)**
```cmd
python warehouse_gateway.py G2021231020
```

**2. Fleet Coordinator (Task Manager)**
```cmd
python fleet_coordinator.py G2021231020
```

**3. System Monitor (Watchdog)**
```cmd
python system_monitor.py G2021231020
```

**4. AMR Robots (Fleet)**
Run each in a separate terminal:
```cmd
python amr_robot.py G2021231020 AMR-1
python amr_robot.py G2021231020 AMR-2
python amr_robot.py G2021231020 AMR-3
python amr_robot.py G2021231020 AMR-4
```

**5. Smart Shelves (Infrastructure)**
Run each in a separate terminal (example for S1 and S6):
```cmd
python shelves.py G2021231020 storage-a S1 5
python shelves.py G2021231020 storage-b S6 5
... (Repeat for S1-S5 in storage-a and S6-S10 in storage-b)
```

**6. MQTT Debugger**
```cmd
python mqtt_debugger.py G2021231020
```

### 2. Inject an Order (See things change!)
To send orders, run the interactive injector:

```cmd
python client_order_injector.py G2021231020
```

You will see a menu with the following options:
1.  **Send Single Order**: Manually specify Item ID (e.g., `item_A`), Quantity, and Station.
2.  **Send Multiple Orders (Batch)**: Send a batch of orders to the same station.
3.  **Send Mixed Orders**: Automatically injects a mix of orders for different items and packing stations (P1-P3) to test routing logic.
4.  **Send Force Charge**: Manually trigger a remote charging command for a specific robot.

**What to expect:**
1.  **Coordinator** receives order (Port 9091).
2.  **Coordinator** finds an IDLE robot (e.g., AMR-1) and a Shelf with `item_A`.
3.  **Coordinator** publishes `EXECUTE_TASK` command.
4.  **Gateway** receives command, encodes it to binary, and forwards to Robot.
5.  **Robot** wakes up, changes state to `MOVING`, and executes the task.
6.  **Grafana**: You will see the robot status change to `MOVING` and a new entry in the Task History.

### 3. Trigger System Monitor Alerts
The System Monitor runs automatically.
-   **Low Battery**: If a robot's battery drops below 15%, the Monitor sends a `FORCE_CHARGE` override. The robot will immediately switch to `CHARGING`.
-   **Stall**: If a robot gets stuck (simulated random failure), the Monitor sends a `STALLED` alert.

## Configuration
All settings are in `config.ini`:
-   MQTT Broker: IP and Port
-   InfluxDB Credentials
-   Ports: Gateway (9090), Coordinator (9091)
