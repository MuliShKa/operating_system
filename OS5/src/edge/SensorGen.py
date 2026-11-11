
import time
import random
from edge.models import SensorEvent

def run_sensor_gen(channels):
    """
    SensorGen process.
    Receives the 'channels' (IpcChannels) object from the Supervisor process.
    """
    print("Started: Sending SensorEvent objects to IPC queue...")

    # Keep running until the supervisor sends the stop signal
    while not channels.stop.is_set():
        # Generate simulated values (water occasionally exceeds 2.8m)
        water_level = round(random.uniform(2.0, 3.5), 2)
        voltage = round(random.uniform(210.0, 230.0), 2)
        current_time = time.time()

        # 1. Create the formal event for water level
        water_event = SensorEvent(
            sensor_id="SLUICE_WATER_LEVEL_M",
            value=water_level,
            unit="m",
            timestamp=current_time
        )
        
        # 2. Create the formal event for voltage
        volt_event = SensorEvent(
            sensor_id="MAINS_VOLT",
            value=voltage,
            unit="V",
            timestamp=current_time
        )

        # Put both events into the queue
        channels.sensor_events.put(water_event)
        channels.sensor_events.put(volt_event)

        print(f"[SensorGen] Queued: {water_event.sensor_id}={water_event.value}{water_event.unit} | {volt_event.sensor_id}={volt_event.value}{volt_event.unit}")

        time.sleep(1)
        
    print("[SensorGen] Stop signal received. Shutting down gracefully.")