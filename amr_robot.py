import sys
import time
import json
import random
import struct
import configparser
from datetime import datetime
import paho.mqtt.client as mqtt

# Load Configuration
config = configparser.ConfigParser()
config.read('config.ini')

BROKER = config['mqtt']['broker']
PORT = int(config['mqtt']['port'])
BATTERY_DECAY = float(config['robot']['battery_decay'])
BATTERY_LOW_THRESHOLD = float(config['robot']['battery_low_threshold'])
ACTIVE_STATES = ["MOVING_TO_PICK", "PICKING", "MOVING_TO_DROP", "DROPPING", "MOVING_TO_CHARGE"]

# State Durations (seconds)
DURATION_MOVING_TO_PICK = 3
DURATION_PICKING = 1
DURATION_MOVING_TO_DROP = 2
DURATION_DROPPING = 1
DURATION_CHARGING = 10

class AMRRobot:
    def __init__(self, group_id, robot_id):
        self.group_id = group_id
        self.robot_id = robot_id
        
        self.topic_status = f"warehouse/{group_id}/amr/{robot_id}/status"
        self.topic_command = f"warehouse/{group_id}/amr/{robot_id}/command"
        
        # Initial State
        self.state = "IDLE"
        self.location = "DOCK"
        self.battery = 100.0
        self.target_shelf = None
        self.target_station = None
        self.state_timer = 0
        self.is_stalled = False
        
        self.client = mqtt.Client(client_id=f"{group_id}-{robot_id}-{random.randint(0, 1000)}")
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect
        
        self.running = True

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print(f"Connected to MQTT Broker as {self.robot_id}")
            client.subscribe(self.topic_command)
        else:
            print(f"Failed to connect, return code {rc}")

    def on_disconnect(self, client, userdata, rc):
        print("Disconnected from MQTT Broker")

    def on_message(self, client, userdata, msg):
        try:
            payload = msg.payload
            
            # Binary Command Parsing (3 Bytes)
            if len(payload) != 3:
                return

            cmd_type, byte2, byte3 = struct.unpack("BBB", payload)
            
            if cmd_type == 0x01: # EXECUTE_TASK
                self.handle_execute_task(byte2, byte3)
            elif cmd_type == 0x03: # FORCE_CHARGE
                self.handle_force_charge()
            else:
                print(f"DEBUG_ROBOT: Unknown command type: {hex(cmd_type)}")
                
        except Exception as e:
            print(f"DEBUG_ROBOT: Error processing message: {e}")

    def handle_execute_task(self, shelf_id, station_id):
        # Validate robot readiness
        if self.is_stalled:
            return
        if self.battery < BATTERY_LOW_THRESHOLD:
            return
        if self.state != "IDLE":
            return

        print(f"DEBUG_ROBOT: Accepted Task: Shelf {shelf_id}, Station {station_id}")
        self.target_shelf = shelf_id
        self.target_station = station_id
        self.transition_to("MOVING_TO_PICK")

    def handle_force_charge(self):
        print("Received FORCE_CHARGE")
        self.is_stalled = False  # Clear stall flag on manual override
        self.transition_to("MOVING_TO_CHARGE")

    def transition_to(self, new_state):
        # State Transition Logic & Location Map
        print(f"Transitioning to {new_state}", flush=True)
        self.state = new_state
        self.state_timer = 0
        
        if new_state == "IDLE":
            self.location = "DOCK"
        elif new_state == "MOVING_TO_PICK":
            self.location = "TRANSIT"
        elif new_state == "PICKING":
            self.location = f"SHELF-S{self.target_shelf}"
        elif new_state == "MOVING_TO_DROP":
            self.location = "TRANSIT"
        elif new_state == "DROPPING":
            self.location = "PACKING_ZONE"
        elif new_state == "MOVING_TO_CHARGE":
            self.location = "TRANSIT"
        elif new_state == "CHARGING":
            self.location = "CHARGING_STATION"

    def update_logic(self):
        # Battery Consumption
        if self.state in ACTIVE_STATES and not self.is_stalled:
            self.battery -= BATTERY_DECAY
            if self.battery < 0: self.battery = 0
        
        # Simulate Random Mechanical Failure (5% chance while moving)
        if "MOVING" in self.state and not self.is_stalled:
            roll = random.random()
            if roll < 0.05: 
                print(f"FAILURE: Robot STALLED (Rolled {roll:.4f} < 0.05)", flush=True)
                self.is_stalled = True

        if self.is_stalled:
            return 

        self.state_timer += 1
        
        # State Machine Progress
        if self.state == "MOVING_TO_PICK":
            if self.state_timer >= DURATION_MOVING_TO_PICK:
                self.transition_to("PICKING")
                
        elif self.state == "PICKING":
            if self.state_timer >= DURATION_PICKING:
                self.transition_to("MOVING_TO_DROP")
                
        elif self.state == "MOVING_TO_DROP":
            if self.state_timer >= DURATION_MOVING_TO_DROP:
                self.transition_to("DROPPING")
                
        elif self.state == "DROPPING":
            if self.state_timer >= DURATION_DROPPING:
                self.transition_to("IDLE")
        
        elif self.state == "MOVING_TO_CHARGE":
             if self.state_timer >= 2:
                 self.transition_to("CHARGING")

        elif self.state == "CHARGING":
            if self.state_timer >= DURATION_CHARGING:
                self.battery = 100.0
                self.transition_to("IDLE")

    def publish_status(self):
        current_status = self.state
        if self.is_stalled:
            current_status = "STALLED"

        status_msg = {
            "robot_id": self.robot_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "location_id": self.location,
            "battery": int(self.battery),
            "status": current_status
        }
        try:
            self.client.publish(self.topic_status, json.dumps(status_msg))
        except Exception as e:
            print(f"Failed to publish status: {e}")

    def run(self):
        try:
            self.client.connect(BROKER, PORT, 60)
            self.client.loop_start()
            
            while self.running:
                start_time = time.time()
                
                self.update_logic()
                self.publish_status()
                
                # Maintain 1Hz Loop Rate
                elapsed = time.time() - start_time
                sleep_time = max(0, 1.0 - elapsed)
                time.sleep(sleep_time)
                
        except KeyboardInterrupt:
            print("Stopping robot...")
        except Exception as e:
            print(f"Unexpected error: {e}")
        finally:
            self.client.loop_stop()
            self.client.disconnect()

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python amr_robot.py {GroupID} {robot_id}")
        sys.exit(1)
        
    group_id = sys.argv[1]
    robot_id = sys.argv[2]
    
    robot = AMRRobot(group_id, robot_id)
    robot.run()
