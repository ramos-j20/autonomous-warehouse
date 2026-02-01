import socket
import sys
import time
import json
import random

def send_udp_message(payload, port=9091):
    target_address = ('127.0.0.1', port)
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(json.dumps(payload).encode('utf-8'), target_address)
        sock.close()
        print(f"Sent to {port}: {payload}")
    except Exception as e:
        print(f"Error sending message: {e}")

def main():
    if len(sys.argv) != 2:
        print("Usage: python client_order_injector.py {GroupID}")
        # Default for testing if not provided, or exit? 
        # Requirement says "Usage: ...", but interactive mode might just need GroupID once.
        # Let's fallback or exit.
        if len(sys.argv) == 1:
             group_id = "G20" # Default
             print(f"No GroupID provided, using default: {group_id}")
        else:
             sys.exit(1)
    else:
        group_id = sys.argv[1]

    while True:
        print("\n--- Client Injector Menu ---")
        print("1. Send Single Order")
        print("2. Send Multiple Orders to same station (Batch)")
        print("3. Send Mixed Orders (P1, P2, P3)")
        print("4. Send Force Charge")
        print("9. Exit")
        
        choice = input("Select option: ")
        
        if choice == '1':
            while True:
                item = input("Item ID (item_A ... item_J): ") or "item_B"
                # Auto-fix commonly made lowercase mistakes
                if item.startswith("item_") and item[-1].islower():
                    item = item[:-1] + item[-1].upper()
                    print(f"Auto-corrected to {item}")
                
                if item.startswith("item_"):
                    break
                print("Invalid Item ID. Must start with 'item_'.")
            
            qty = input("Quantity (e.g., 10): ") or "10"
            
            while True:
                station = input("Pack Station (P1, P2, P3): ") or "P1"
                if station in ["P1", "P2", "P3"]:
                    break
                print("Invalid Station. Must be P1, P2, or P3.")
            
            order = {
                "item": item,
                "quantity": int(qty),
                "pack_station": station,
                "order_id": f"ord-{int(time.time()*1000)}"
            }
            send_udp_message(order, port=9091)
            
        elif choice == '2':
            # Batch
            count = int(input("How many orders? ") or "4")
            
            while True:
                item = input("Item ID (item_A ... item_J): ") or "item_B"
                if item.startswith("item_") and item[-1].islower():
                    item = item[:-1] + item[-1].upper()
                    print(f"Auto-corrected to {item}")
                    
                if item.startswith("item_"):
                    break
                print("Invalid Item ID. Must start with 'item_'.")
                
            qty = input("Quantity per Order (e.g., 10): ") or "10"
            
            while True:
                station = input("Pack Station (P1, P2, P3): ") or "P1"
                if station in ["P1", "P2", "P3"]:
                    break
                print("Invalid Station. Must be P1, P2, or P3.")
            
            for i in range(count):
                order = {
                    "item": item,
                    "quantity": int(qty),
                    "pack_station": station,
                    "order_id": f"ord-{int(time.time()*1000)}-{i}"
                }
                send_udp_message(order, port=9091)
                # Small delay to ensure separate UDP packets
                time.sleep(0.1)
                
        elif choice == '3':
            # NEW: Mixed Station Test with Zone Crossing
            print("Sending 6 orders: Mixed Stations (P1-P3) AND Mixed Zones (Storage A/B)")
            stations = ["P1", "P2", "P3"]
            items = ["item_A", "item_F"] # item_A=S1(StorageA), item_F=S6(StorageB)
            
            for i in range(6):
                target_station = stations[i % 3]
                target_item = items[i % 2] # Alternates A, F, A, F...
                
                print(f"Injecting: {target_item} -> {target_station}")
                order = {
                    "item": target_item,
                    "quantity": 5,
                    "pack_station": target_station,
                    "order_id": f"ord-mix-{int(time.time())}-{i}"
                }
                send_udp_message(order, port=9091)
                time.sleep(0.5) # Slower injection to observe routing

        elif choice == '4':
            # Force Charge (To Monitor -> Gateway -> Robot)
            r_id = input("Robot ID (e.g. AMR-1): ") or "AMR-1"
            payload = {
                "robot_id": r_id,
                "level": "CRITICAL",
                "override_task": "FORCE_CHARGE"
            }
            g_port = int(input("Gateway UDP Port (default 9090? Check gateway): ") or "9090")
            send_udp_message(payload, port=g_port)

        elif choice == '9':
            print("Exiting.")
            break

if __name__ == "__main__":
    main()
