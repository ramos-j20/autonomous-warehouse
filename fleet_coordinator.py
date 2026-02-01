import sys
import json
import time
import socket
import select
import random
import configparser
import paho.mqtt.client as mqtt
from collections import deque

# Load Configuration
config = configparser.ConfigParser()
config.read('config.ini')

MQTT_BROKER = config.get('mqtt', 'broker', fallback='localhost')
MQTT_PORT = config.getint('mqtt', 'port', fallback=1883)
INITIAL_STOCK = config.getint('shelf', 'initial_stock', fallback=100)
GROUP_ID = "G2021231020" 

class FleetCoordinator:
    def __init__(self, group_id):
        self.group_id = group_id
        
        # Track simulated world state
        self.world_state = {
            "robots": {},   
            "shelves": {},  
        }
        
        self.pending_orders = deque() 
        self.active_stations = set() # Set of currently busy station IDs
        self.robot_assignments = {} 

        self.mqtt_client = mqtt.Client(client_id=f"coordinator-{group_id}-{int(time.time())}")
        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.on_message = self.on_message
        
        # UDP Server for Client Orders
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.bind(('0.0.0.0', 9091))
        self.udp_socket.setblocking(False) 
        
        self.last_no_stock_log = 0 
        print(f"[{self.group_id}] Fleet Coordinator initialized. Broker: {MQTT_BROKER}:{MQTT_PORT}")

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print("Connected to MQTT Broker")
            # Subscribe to all internal status updates
            topic_filter = f"{self.group_id}/internal/+/+/status"
            client.subscribe(topic_filter)
            print(f"Subscribed to {topic_filter}")
        else:
            print(f"Failed to connect to MQTT, rc={rc}")

    def on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode('utf-8'))
            topic_parts = msg.topic.split('/')
            
            if len(topic_parts) < 5:
                return

            category = topic_parts[2] 
            entity_id = topic_parts[3] 
            
            # Route matched messages to update handlers
            if category == "amr":
                self.update_robot_state(entity_id, payload)
            elif category == "static" or category == "shelves":
                self.update_shelf_state(entity_id, payload)
                
        except Exception as e:
            print(f"Error processing MQTT message on {msg.topic}: {e}")

    def update_robot_state(self, robot_id, payload):
        status = payload.get("status")
        
        # Track internal state to handle task lifecycle logic
        current_internal_state = "FREE"
        if robot_id in self.world_state["robots"]:
            current_internal_state = self.world_state["robots"][robot_id].get("internal_state", "FREE")
            
        # HANDLE STALLS: Robot reported failure
        if status == "STALLED":
            if current_internal_state in ["ASSIGNED", "WORKING"]:
                print(f"CRITICAL: Robot {robot_id} reported STALLED while {current_internal_state}!")
                
                # Recover Order from Stalled Robot
                if robot_id in self.robot_assignments:
                    assignment = self.robot_assignments[robot_id]
                    failed_order = assignment.get("order")
                    station_id = assignment.get("station")
                    shelf_id = assignment.get("shelf_id")
                    qty = assignment.get("quantity", 0)

                    # Refund stock if robot had arguably picked it
                    if current_internal_state == "WORKING" and shelf_id:
                        print(f"REFUNDING {qty} items to {shelf_id} (Robot Stalled while working)")
                        refund_payload = {
                            "command": "RESTOCK",
                            "target_shelf_id": shelf_id,
                            "quantity": qty
                        }
                        self.mqtt_client.publish(f"{self.group_id}/internal/tasks/dispatch", json.dumps(refund_payload), qos=1)
                    
                    # Re-queue the failed order to be picked up by another robot
                    if failed_order:
                        print(f"REQUEUING Order due to Stall: {failed_order}")
                        self.pending_orders.appendleft(failed_order)
                    
                    # Force unlock station so others can use it
                    if station_id in self.active_stations:
                        self.active_stations.remove(station_id)
                        print(f"Force-Released Station {station_id} due to stall.")
                    
                    del self.robot_assignments[robot_id]
                
                current_internal_state = "STALLED"
        
        # Task started confirmation
        elif current_internal_state == "ASSIGNED":
            if status in ["MOVING_TO_PICK", "PICKING", "MOVING_TO_DROP", "DROPPING"]:
                 current_internal_state = "WORKING"

        # Task completion: Robot went back to IDLE
        elif current_internal_state == "WORKING":
            if status == "IDLE":
                self.free_station(robot_id)
                current_internal_state = "FREE"

        # Recovery from Stall
        elif current_internal_state == "STALLED":
            if status == "IDLE":
                current_internal_state = "FREE"

        self.world_state["robots"][robot_id] = payload
        self.world_state["robots"][robot_id]["internal_state"] = current_internal_state

    def update_shelf_state(self, shelf_id, payload):
        self.world_state["shelves"][shelf_id] = payload

    def free_station(self, robot_id):
        # Unlocks the packing station resource
        if robot_id in self.robot_assignments:
            assignment = self.robot_assignments.pop(robot_id)
            station_id = assignment.get("station") if isinstance(assignment, dict) else assignment
            
            if station_id in self.active_stations:
                self.active_stations.remove(station_id)
                print(f"Released Station {station_id} (Robot {robot_id} finished)")

    def process_orders(self):
        # Attempt to process all pending orders
        if not self.pending_orders:
            return

        count = len(self.pending_orders)
        for _ in range(count):
            order = self.pending_orders.popleft()
            if self.try_match_order(order):
                pass
            else:
                self.pending_orders.append(order)

    def try_match_order(self, order):
        target_item = order.get("item")
        target_station = order.get("pack_station", "").strip()
        
        # Check if Station is Busy
        if target_station and target_station in self.active_stations:
             return False

        # Find Shelf with Stock
        target_shelf_id = None
        for shelf_id, data in self.world_state["shelves"].items():
            if data.get("item_id") == target_item:
                try:
                    if float(data.get("stock", 0)) > 0:
                        target_shelf_id = shelf_id
                        break
                except ValueError:
                    pass
        
        if not target_shelf_id:
            now = time.time()
            if now - self.last_no_stock_log > 5:
                self.last_no_stock_log = now
            return False

        # Find Available Robot
        eligible_robots = []
        for robot_id, data in self.world_state["robots"].items():
            internal_st = data.get("internal_state", "FREE")
            remote_st = data.get("status")
            
            if remote_st == "IDLE" and internal_st == "FREE":
                eligible_robots.append(robot_id)
        
        if not eligible_robots:
            return False
            
        assigned_robot_id = random.choice(eligible_robots)

        qty = order.get("quantity", 1)
        
        # Boost stock if insufficient for order (Auto-Refill Trigger)
        try:
             current_stock = float(self.world_state["shelves"][target_shelf_id].get("stock", 0))
             while current_stock < qty:
                 print(f"Stock {current_stock} < Order {qty}. Triggering Auto-Refill...")
                 restock_payload = {
                    "command": "RESTOCK",
                    "target_shelf_id": target_shelf_id,
                    "quantity": INITIAL_STOCK
                 }
                 self.mqtt_client.publish(f"{self.group_id}/internal/tasks/dispatch", json.dumps(restock_payload), qos=1)
                 
                 current_stock += INITIAL_STOCK
             
             self.world_state["shelves"][target_shelf_id]["stock"] = current_stock
             
        except Exception as e:
            print(f"Error in auto-refill logic: {e}")

        # Finalize assignment and lock resources
        self.dispatch_task(assigned_robot_id, target_shelf_id, target_station, qty, order)
        return True

    def dispatch_task(self, robot_id, shelf_id, station_id, quantity, full_order):
        # Lock Station
        self.active_stations.add(station_id)
        
        self.robot_assignments[robot_id] = {
            "station": station_id,
            "shelf_id": shelf_id,
            "quantity": quantity,
            "order": full_order
        }
        
        # Reserve Robot locally to prevent double assignment
        if robot_id in self.world_state["robots"]:
            self.world_state["robots"][robot_id]["status"] = "ASSIGNED"
            self.world_state["robots"][robot_id]["internal_state"] = "ASSIGNED"

        payload = {
            "robot_id": robot_id,
            "command": "EXECUTE_TASK",
            "target_shelf_id": shelf_id,
            "target_station_id": station_id,
            "quantity": quantity
        }
        
        topic = f"{self.group_id}/internal/tasks/dispatch"
        
        oid = full_order.get("order_id", "unknown")
        print(f"DISPATCHING Order {oid}: {json.dumps(payload)}")
        
        info = self.mqtt_client.publish(topic, json.dumps(payload), qos=1)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            print(f"WARNING: Publish failed with code {info.rc}")

    def print_world_state(self):
        print("\n--- World State ---")
        print(f"Pending Orders: {len(self.pending_orders)}")
        if self.pending_orders:
            print(f"  Next: {list(self.pending_orders)[0]}")
        
        print(f"Active Stations: {self.active_stations}")
        
        assigned_count = sum(1 for r in self.world_state["robots"].values() if r.get("status") != "IDLE")
        print(f"Robots Busy: {assigned_count}/{len(self.world_state['robots'])}")
        
        print("-------------------\n")
        print("-------------------\n")

    def run(self):
        try:
            print(f"Connecting to MQTT {MQTT_BROKER}...")
            self.mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
            self.mqtt_client.loop_start() 
            
            print("Coordinator Loop Started (CTRL+C to stop)")
            last_heartbeat = time.time()
            
            while True:
                if time.time() - last_heartbeat > 5:
                    self.print_world_state()
                    last_heartbeat = time.time()

                # Check for new UDP orders
                readable, _, _ = select.select([self.udp_socket], [], [], 0.1)
                
                for s in readable:
                    if s is self.udp_socket:
                        try:
                            data, addr = self.udp_socket.recvfrom(1024)
                            order = json.loads(data.decode('utf-8'))
                            # Sanitize input
                            if "item" in order: order["item"] = order["item"].strip()
                            print(f"UDP Received Order: {order.get('order_id', 'unknown')} | {order.get('item')} x{order.get('quantity')}")
                            self.pending_orders.append(order)
                        except Exception as e:
                            print(f"UDP Error: {e}")

                self.process_orders()
                
        except KeyboardInterrupt:
            print("Stopping...")
        finally:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()

if __name__ == "__main__":
    g_id = sys.argv[1] if len(sys.argv) > 1 else GROUP_ID
    coord = FleetCoordinator(g_id)
    coord.run()
