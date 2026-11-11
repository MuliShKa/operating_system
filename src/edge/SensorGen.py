
import time
import random
from edge.models import SensorEvent

def run_sensor_gen(channels):
    """
    Generate simulated sensor readings and send them to the shared IPC queue.

    The supervisor passes the shared IpcChannels instance to this process;
    its stop event lets the worker exit cooperatively during shutdown.
    """
    print("Started: Sending SensorEvent objects to IPC queue...")

    # Keep running until the supervisor sends the stop signal
    while not channels.stop.is_set():
        # Generate realistic demo values; water readings can cross the 2.8 m
        # decision threshold, while voltage stays in a typical mains range.
        water_level = round(random.uniform(2.0, 3.5), 2)
        voltage = round(random.uniform(210.0, 230.0), 2)
        current_time = time.time()

        # Package each reading with a sensor identifier, unit, and timestamp
        # so downstream code can process both sensor types uniformly.
        water_event = SensorEvent(
            sensor_id="SLUICE_WATER_LEVEL_M",
            value=water_level,
            unit="m",
            timestamp=current_time
        )
        
        volt_event = SensorEvent(
            sensor_id="MAINS_VOLT",
            value=voltage,
            unit="V",
            timestamp=current_time
        )

        # Both events use the same sample time and preserve their queue order.
        channels.sensor_events.put(water_event)
        channels.sensor_events.put(volt_event)

        print(f"[SensorGen] Queued: {water_event.sensor_id}={water_event.value}{water_event.unit} | {volt_event.sensor_id}={volt_event.value}{volt_event.unit}")

        # Limit the demo sampling rate to one pair of readings per second.
        time.sleep(1)
        
    print("[SensorGen] Stop signal received. Shutting down gracefully.")