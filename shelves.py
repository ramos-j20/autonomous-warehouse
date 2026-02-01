import sys
import time
import json
import random
import configparser
import paho.mqtt.client as mqtt

# Load Configuration
config = configparser.ConfigParser()
config.read('config.ini')

BROKER = config['mqtt']['broker']
PORT = int(config['mqtt']['port'])
INITIAL_STOCK = int(config['shelf']['initial_stock'])

class ShelfSensor:
    def __init__(self, group_id, zone_id, asset_id, update_time):
        self.group_id = group_id
        self.zone_id = zone_id
        self.asset_id = asset_id
        self.update_time = float(update_time)
        
        self.topic = f"warehouse/{group_id}/locations/{zone_id}/{asset_id}/status"
        
        # State Tracking
        self.pending_robots = set() # Robots en route
        self.deduction_queue = []   # Quantity reserved for incoming robots
        self.processed_robots = set() 

        # Parse Shelf ID (e.g., S1 -> 1)
        try:
            self.shelf_num = int(asset_id[1:])
        except ValueError:
            self.shelf_num = 1 
            
        self.item_id = f"item_{chr(64 + self.shelf_num)}"
        
        # Assign Units based on Zone
        if zone_id == "storage-a":
            self.unit = "units"
        elif zone_id == "storage-b":
            self.unit = "kg"
        else:
            self.unit = "units" 
            
        self.stock = INITIAL_STOCK
        
        self.client = mqtt.Client(client_id=f"{group_id}-{asset_id}-{random.randint(0, 1000)}")
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect
        
        self.running = True

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print(f"Connected to MQTT Broker as {self.asset_id}")
            client.subscribe(f"{self.group_id}/internal/tasks/dispatch")
            client.subscribe(f"{self.group_id}/internal/amr/+/status")
        else:
            print(f"Failed to connect, return code {rc}")

    def on_disconnect(self, client, userdata, rc):
        print("Disconnected from MQTT Broker")

    def on_message(self, client, userdata, msg):
        try:
            topic = msg.topic
            payload = json.loads(msg.payload.decode('utf-8'))
            
            # HANDLE TASK DISPATCH (Reservation)
            if "tasks/dispatch" in topic:
                command = payload.get("command", "") 
                target_shelf = payload.get("target_shelf_id")
                quantity = payload.get("quantity", 0)
                robot_id = payload.get("robot_id")
                
                if target_shelf == self.asset_id:
                    if command == "RESTOCK":
                        self.stock += quantity
                        print(f"RESTOCK Received: Added {quantity} {self.unit}. New Stock: {self.stock}")
                        self.publish_status()
                    else:
                        # Reserve stock for incoming pickup
                        if robot_id:
                            self.pending_robots.add(robot_id)
                        
                        self.deduction_queue.append(quantity)
                        print(f"Order received for {robot_id}. Reserved {quantity} {self.unit}. Pending Pick: {len(self.pending_robots)}")

            # HANDLE ROBOT STATUS (Physical Pick Detection)
            elif "status" in topic and "amr" in topic:
                topic_parts = topic.split('/')
                if len(topic_parts) >= 4:
                    robot_id = topic_parts[3]
                else:
                    robot_id = payload.get("robot_id")

                if not robot_id: return

                r_status = payload.get("status")
                r_location = payload.get("location_id") 
                expected_loc = f"SHELF-{self.asset_id}"
                
                # Deduct stock when robot is physically "PICKING" at this shelf
                if r_status == "PICKING" and r_location == expected_loc:
                    if robot_id not in self.processed_robots:
                        self.process_deduction(robot_id)
                        self.processed_robots.add(robot_id)
                        if robot_id in self.pending_robots:
                            self.pending_robots.remove(robot_id)
                    else:
                        pass
                
                # Handle Robot Failure (Cancel Reservation)
                elif r_status == "STALLED":
                    if robot_id in self.pending_robots:
                        print(f"Robot {robot_id} STALLED! Removing from Pending List.")
                        self.pending_robots.remove(robot_id)
                        
                        if self.deduction_queue:
                            self.deduction_queue.pop(0) 
                            print("Removed ghost reservation from queue.")

                else:
                    if robot_id in self.processed_robots:
                        self.processed_robots.remove(robot_id)

        except Exception as e:
            print(f"Error processing message: {e}")

    def process_deduction(self, robot_id):
        # Apply FIFO deduction
        if self.deduction_queue:
            qty_to_deduct = self.deduction_queue.pop(0)
            
            print(f"Robot {robot_id} Picking! Deducting {qty_to_deduct} {self.unit}.")
            self.stock -= qty_to_deduct
            if self.stock < 0: self.stock = 0
            
            self.publish_status()
        else:
             print(f"Robot {robot_id} arrived but no queued deductions?")

    def publish_status(self):
        msg = {
            "asset_id": self.asset_id,
            "type": "SHELF",
            "item_id": self.item_id,
            "stock": self.stock,
            "unit": self.unit,
        }
        try:
            self.client.publish(self.topic, json.dumps(msg))
            print(f"Published: {msg}")
        except Exception as e:
            print(f"Failed to publish: {e}")

    def run(self):
        try:
            self.client.connect(BROKER, PORT, 60)
            self.client.loop_start()
            
            while self.running:
                self.publish_status()
                
                # Auto-Refill Logic (<25%)
                if self.stock < (INITIAL_STOCK * 0.25):
                    print(f"Stock low ({self.stock}). Refilling in 2 seconds...")
                    time.sleep(2)
                    self.stock = INITIAL_STOCK
                    print("Refilled.")
                
                time.sleep(self.update_time)
                
        except KeyboardInterrupt:
            print("Stopping shelf sensor...")
        except Exception as e:
            print(f"Unexpected error: {e}")
        finally:
            self.client.loop_stop()
            self.client.disconnect()

if __name__ == "__main__":
    if len(sys.argv) != 5:
        print("Usage: python shelves.py {GroupID} {zone_id} {asset_id} {update_time}")
        sys.exit(1)
        
    group_id = sys.argv[1]
    zone_id = sys.argv[2]
    asset_id = sys.argv[3]
    update_time = sys.argv[4]
    
    sensor = ShelfSensor(group_id, zone_id, asset_id, update_time)
    sensor.run()
