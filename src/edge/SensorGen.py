import time
import random

def main():
    print("Inicializing local SensorGen")
    while True:
        water_level = round(random.uniform(2.0, 3.5), 2)
        voltage = round(random.uniform(210, 230), 2)

        print(f"SLUICE_WATER_LEVEL_M: {water_level} m | MAINS_VOLT: {voltage} V")

        time.sleep(2)

if __name__ == "__main__":
    main()