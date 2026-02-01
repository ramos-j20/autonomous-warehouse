import sys
import time
import json
import datetime
import configparser
import paho.mqtt.client as mqtt

# Load Configuration
config = configparser.ConfigParser()
config.read('config.ini')

BROKER = config['mqtt']['broker']
PORT = int(config['mqtt']['port'])

class MQTTDebugger:
    def __init__(self, group_id):
        self.group_id = group_id
        
        # Topics
        self.topic_warehouse = f"warehouse/{group_id}/#"
        self.topic_internal = f"{group_id}/internal/#"
        
        # MQTT Client
        self.client = mqtt.Client(client_id=f"debugger-{group_id}-{int(time.time())}")
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect
        
    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print(f"Connected to MQTT Broker. Subscribing to:")
            print(f" - # (ALL)")
            client.subscribe("#")
        else:
            print(f"Failed to connect, return code {rc}")

    def on_disconnect(self, client, userdata, rc):
        print("Disconnected from MQTT Broker")

    def on_message(self, client, userdata, msg):
        try:
            timestamp = datetime.datetime.now().isoformat()
            topic = msg.topic
            payload = msg.payload
            
            decoded_msg = None
            is_binary = False
            
            # Try decoding as UTF-8 string first
            try:
                str_payload = payload.decode('utf-8')
                # Try parsing as JSON
                try:
                    json_payload = json.loads(str_payload)
                    decoded_msg = json.dumps(json_payload, indent=None) # Compact JSON for one-line log
                except json.JSONDecodeError:
                    decoded_msg = str_payload
            except UnicodeDecodeError:
                is_binary = True
                decoded_msg = f"BINARY: {payload.hex()}"
            
            print(f"[{timestamp}]: {topic}: {decoded_msg}")
            
        except Exception as e:
            print(f"Error processing message: {e}")

    def run(self):
        try:
            self.client.connect(BROKER, PORT, 60)
            self.client.loop_forever()
        except KeyboardInterrupt:
            print("\nStopping debugger...")
        except Exception as e:
            print(f"Unexpected error: {e}")
        finally:
            self.client.disconnect()

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python mqtt_debugger.py {GroupID}")
        sys.exit(1)
        
    group_id = sys.argv[1]
    
    debugger = MQTTDebugger(group_id)
    debugger.run()
