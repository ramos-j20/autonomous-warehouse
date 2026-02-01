import logging
import asyncio
from amqtt.broker import Broker

# Configuration for the broker
config = {
    'listeners': {
        'default': {
            'type': 'tcp',
            'bind': '0.0.0.0:1883',
        },
    },
    'sys_interval': 10,
    'auth': {
        'allow_anonymous': True,
        'password_file': '',
        'plugins': [
            'auth_anonymous'
        ]
    }
}

async def start_broker():
    broker = Broker(config)
    await broker.start()
    print("Local MQTT Broker started on port 1883...", flush=True)
    # Keep the broker running
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("Stopping broker...")
        await broker.shutdown()

if __name__ == "__main__":
    formatter = "[%(asctime)s] %(name)s {%(filename)s:%(lineno)d} %(levelname)s - %(message)s"
    logging.basicConfig(level=logging.INFO, format=formatter, filename='broker.log', filemode='w')
    
    # Run the broker
    asyncio.run(start_broker())
