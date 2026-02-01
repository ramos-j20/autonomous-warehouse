import sys
import json
import time
import configparser
from datetime import datetime
import paho.mqtt.client as mqtt
import socket
import struct
import threading
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import WriteOptions

# Load Configuration
config = configparser.ConfigParser()
config.read('config.ini')

MQTT_BROKER = config['mqtt']['broker']
MQTT_PORT = int(config['mqtt']['port'])

INFLUX_URL = config['influxdb']['url']
INFLUX_TOKEN = config['influxdb']['token']
INFLUX_ORG = config['influxdb']['org']
INFLUX_BUCKET = config['influxdb']['bucket']

class WarehouseGateway:
    def __init__(self, group_id):
        self.group_id = group_id
        
        # Initialize MQTT Client for bidirectional communication
        self.mqtt_client = mqtt.Client(client_id=f"gateway-{group_id}-{int(time.time())}")
        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.on_message = self.on_message
        self.mqtt_client.on_subscribe = self.on_subscribe 
        
        # Initialize InfluxDB Client with batching for efficiency
        self.influx_client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
        self.write_api = self.influx_client.write_api(write_options=WriteOptions(batch_size=10, flush_interval=1000))
        
        # UDP Server to listen for critical override commands from Monitor
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.bind(('0.0.0.0', 9090))
        self.udp_running = True
        
        print(f"Gateway initialized for Group {group_id}")

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print("Connected to MQTT Broker")
            # Subscribe to all telemetry topics to act as ETL
            client.subscribe(f"warehouse/{self.group_id}/#")
            # Subscribe to Coordinator commands to forward them to robots
            client.subscribe(f"{self.group_id}/internal/tasks/dispatch")
            print(f"Subscribed to warehouse/{self.group_id}/# and {self.group_id}/internal/tasks/dispatch")
        else:
            print(f"Failed to connect to MQTT, rc={rc}")

    def on_subscribe(self, client, userdata, mid, granted_qos):
        print(f"DEBUG Gateway: Subscribed to topic (MsgID: {mid}, QoS: {granted_qos})")

    def on_message(self, client, userdata, msg):
        try:
            topic = msg.topic
            
            # Avoid processing own binary commands to prevent loops
            if topic.endswith("/command"):
                return

            payload = json.loads(msg.payload.decode('utf-8'))
            
            parts = topic.split('/')
            
            # Route based on source entity
            if "amr" in parts:
                self.process_robot_message(topic, payload)
            elif "locations" in parts:
                self.process_shelf_message(topic, payload)
            elif "tasks" in parts and "dispatch" in parts:
                self.process_dispatch_command(payload)
                
        except json.JSONDecodeError:
            print(f"Failed to decode JSON from {msg.topic}")
        except Exception as e:
            print(f"Error processing message: {e}")

    def process_robot_message(self, topic, payload):
        # Forward robot status to internal logic topics and DB
        try:
            robot_id = payload.get("robot_id")
            if not robot_id: return

            internal_topic = f"{self.group_id}/internal/amr/{robot_id}/status"
            self.mqtt_client.publish(internal_topic, json.dumps(payload))
            
            point = Point("robot_status") \
                .tag("group_id", self.group_id) \
                .tag("robot_id", robot_id) \
                .field("battery", float(payload.get("battery", 0))) \
                .field("location_id", payload.get("location_id", "UNKNOWN")) \
                .field("status", payload.get("status", "UNKNOWN"))
                
            self.write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=point)
            
        except Exception as e:
            print(f"Error in robot processing: {e}")

    def process_shelf_message(self, topic, payload):
        # Normalize stock units to KG and log to DB
        try:
            parts = topic.split('/')
            zone_id = parts[3]
            asset_id = parts[4]
            
            stock = float(payload.get("stock", 0))
            unit = payload.get("unit", "units")
            
            # Unit Conversion Logic
            stock_kg = stock
            if unit == "units":
                stock_kg = stock * 23.0
            
            cleaned_payload = payload.copy()
            cleaned_payload["stock"] = stock_kg
            cleaned_payload["unit"] = "kg"
            cleaned_payload["original_stock"] = stock
            cleaned_payload["original_unit"] = unit
            
            internal_topic = f"{self.group_id}/internal/static/{asset_id}/status"
            self.mqtt_client.publish(internal_topic, json.dumps(cleaned_payload))
            
            point = Point("shelf_status") \
                .tag("group_id", self.group_id) \
                .tag("zone_id", zone_id) \
                .tag("asset_id", asset_id) \
                .tag("item_id", payload.get("item_id", "UNKNOWN")) \
                .field("stock_kg", stock_kg)
                
            self.write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=point)
            
        except Exception as e:
            print(f"Error in shelf processing: {e}")

    def process_dispatch_command(self, payload):
        # Convert high-level JSON tasks to low-level binary commands
        try:
            robot_id = payload.get("robot_id")
            command_str = payload.get("command")
            target_shelf = payload.get("target_shelf_id")
            target_station = payload.get("target_station_id")
            
            if not all([robot_id, command_str, target_shelf, target_station]):
                print("Invalid dispatch payload")
                return

            quantity = payload.get("quantity", 1)

            if command_str == "EXECUTE_TASK":
                self.send_robot_command(robot_id, 0x01, target_shelf, target_station, quantity)
                print(f"DEBUG Gateway: Dispatched EXECUTE_TASK to {robot_id} (Shelf {target_shelf}, Station {target_station}, Qty {quantity})")
                
        except Exception as e:
            print(f"Error processing dispatch: {e}")

    def start_udp_server(self):
        # Background thread for handling UDP overrides
        print("UDP Server listening on port 9090...")
        while self.udp_running:
            try:
                data, addr = self.udp_socket.recvfrom(1024)
                payload = json.loads(data.decode('utf-8'))
                self.process_udp_message(payload)
            except socket.timeout:
                continue
            except Exception as e:
                print(f"UDP Error: {e}")

    def process_udp_message(self, payload):
        try:
            robot_id = payload.get("robot_id")
            override_task = payload.get("override_task")
            
            point = Point("system_alerts") \
                .tag("group_id", self.group_id) \
                .tag("robot_id", robot_id) \
                .tag("level", payload.get("level", "INFO")) \
                .field("message", f"Override: {override_task}")
            self.write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=point)
            
            if override_task == "FORCE_CHARGE":
                # Send binary override command (0x03)
                self.send_robot_command(robot_id, 0x03, "S0", "P0")
                print(f"Sent FORCE_CHARGE override to {robot_id}")
                
        except Exception as e:
            print(f"Error processing UDP override: {e}")

    def send_robot_command(self, robot_id, cmd_byte, shelf_id_str, station_id_str, quantity=0):
        # Pack command into 3-byte binary struct for bandwidth efficiency
        try:
            shelf_id = self.extract_id(shelf_id_str)
            station_id = self.extract_id(station_id_str)
            
            payload = struct.pack("BBB", cmd_byte, shelf_id, station_id)
            
            topic = f"warehouse/{self.group_id}/amr/{robot_id}/command"
            self.mqtt_client.publish(topic, payload)
            
            cmd_type_str = "EXECUTE_TASK" if cmd_byte == 0x01 else "FORCE_CHARGE" if cmd_byte == 0x03 else "UNKNOWN"
            point = Point("robot_commands") \
                .tag("group_id", self.group_id) \
                .tag("robot_id", robot_id) \
                .field("command_type", cmd_type_str) \
                .field("target_shelf", str(shelf_id_str)) \
                .field("target_station", str(station_id_str)) \
                .field("quantity", int(quantity))
            self.write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=point)
            
        except Exception as e:
            print(f"Error sending robot command: {e}")

    def extract_id(self, id_str):
        # Helper to extract integer ID from string (e.g. "S1" -> 1)
        import re
        match = re.search(r'\d+', str(id_str))
        return int(match.group()) if match else 0

    def run(self):
        try:
            udp_thread = threading.Thread(target=self.start_udp_server, daemon=True)
            udp_thread.start()
            
            self.mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
            self.mqtt_client.loop_forever()
        except KeyboardInterrupt:
            print("Stopping Gateway...")
        except Exception as e:
            print(f"Unexpected error: {e}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python warehouse_gateway.py {GroupID}")
        sys.exit(1)
        
    group_id = sys.argv[1]
    gateway = WarehouseGateway(group_id)
    gateway.run()
