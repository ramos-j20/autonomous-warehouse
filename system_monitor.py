import json
import time
import socket
import configparser
import sys
import paho.mqtt.client as mqtt

# Load Configuration
config = configparser.ConfigParser()
config.read('config.ini')

MQTT_BROKER = config['mqtt']['broker']
MQTT_PORT = int(config['mqtt']['port'])

class SystemMonitor:
    def __init__(self, group_id):
        self.group_id = group_id
        
        # State tracking for anomaly detection
        self.robot_states = {}
        
        self.mqtt_client = mqtt.Client(client_id=f"monitor-{group_id}-{int(time.time())}")
        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.on_message = self.on_message
        
        # UDP Socket (Sender) to Gateway
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.gateway_address = ('127.0.0.1', 9090)
        
        print(f"System Monitor initialized for Group {group_id}")

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print("Connected to MQTT Broker")
            topic = f"{self.group_id}/internal/amr/+/status"
            client.subscribe(topic)
            print(f"Subscribed to {topic}")
        else:
            print(f"Failed to connect to MQTT, rc={rc}")

    def on_message(self, client, userdata, msg):
        try:
            topic = msg.topic
            payload = json.loads(msg.payload.decode('utf-8'))
            
            parts = topic.split('/')
            if len(parts) >= 5 and parts[2] == 'amr':
                robot_id = parts[3]
                self.process_robot_status(robot_id, payload)
                
        except Exception as e:
            print(f"Error processing message: {e}")

    def process_robot_status(self, robot_id, payload):
        # ANOMALY DETECTION LOGIC
        current_status = payload.get("status")
        current_location = payload.get("location_id")
        current_battery = float(payload.get("battery", 0))
        now = time.time()
        
        if robot_id not in self.robot_states:
            self.robot_states[robot_id] = {
                "last_location": current_location,
                "last_move_time": now,
                "status": current_status,
                "battery": current_battery
            }
            return

        state = self.robot_states[robot_id]
        
        # Check for Stalled Robots
        if current_status == "STALLED":
            time_stalled = now - state["last_move_time"]
            if time_stalled >= 30:
                print(f"CRITICAL: Robot {robot_id} reported STALLED for {int(time_stalled)}s. Sending FORCE_CHARGE.")
                self.send_override(robot_id, "STALLED_REPORT")
                state["last_move_time"] = now # Reset timer
            else:
                if int(time_stalled) % 5 == 0:
                    print(f"DEBUG: Robot {robot_id} STALLED. Timeout: {int(time_stalled)}/30s")
        
        # Check for Stuck Robots (Moving but not changing location)
        elif "MOVING" in current_status:
            if current_location != state["last_location"]:
                # Movement detected, reset timer
                state["last_location"] = current_location
                state["last_move_time"] = now
            else:
                time_stalled = now - state["last_move_time"]
                
                if time_stalled >= 30:
                    print(f"CRITICAL: Robot {robot_id} STUCK for {int(time_stalled)}s")
                    self.send_override(robot_id, "STUCK_TIMEOUT")
                    state["last_move_time"] = now 
        else:
            state["last_move_time"] = now
            state["last_location"] = current_location

        # Check for Critical Battery Levels
        last_alert = state.get("last_alert", 0)
        if current_battery < 15.0 and current_status not in ["CHARGING", "MOVING_TO_CHARGE"]:
            if (now - last_alert) > 10.0: # Debounce alerts (10s)
                print(f"CRITICAL: Robot {robot_id} LOW BATTERY ({current_battery}%)")
                self.send_override(robot_id, "LOW_BATTERY")
                state["last_alert"] = now
            
        # Update local state
        state["status"] = current_status
        state["battery"] = current_battery

    def send_override(self, robot_id, reason):
        # Send UDP Packet to Gateway to trigger immediate action
        msg = {
            "robot_id": robot_id,
            "level": "CRITICAL",
            "override_task": "FORCE_CHARGE"
        }
        try:
            self.udp_socket.sendto(json.dumps(msg).encode('utf-8'), self.gateway_address)
            print(f"Sent UDP Override for {robot_id} (Reason: {reason})")
        except Exception as e:
            print(f"Failed to send UDP override: {e}")

    def run(self):
        try:
            self.mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
            self.mqtt_client.loop_forever()
        except KeyboardInterrupt:
            print("Stopping Monitor...")
        except Exception as e:
            print(f"Unexpected error: {e}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python system_monitor.py {GroupID}")
        sys.exit(1)
        
    group_id = sys.argv[1]
    monitor = SystemMonitor(group_id)
    monitor.run()
