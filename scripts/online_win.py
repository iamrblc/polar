###################
# PACKAGE IMPORTS #
###################

# Generic stuff
import yaml					# To access config
from pathlib import Path	# To handle paths
import platform				# To assess OS
import csv					# To create csv output				
import time					# Time is money. 
from datetime import datetime as dt # To make timestamps

# Communication with the device
from bleak import BleakClient # For bluetooth connection
import asyncio
import msvcrt


##########
# SETUPS #
##########

# PATHS
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CONFIG = ROOT / "scripts" / "config.yaml"

#LOAD CONFIGS
with open (CONFIG, "r") as f:
    config = yaml.safe_load(f)

# BELT
# On Mac it's identified using UUID, on Win and Linux with MAC address
os = platform.system()          
BELT = config["belt"]["uuid"] if os == "Darwin" else config["belt"]["mac_address"]
belt_human_readable = config["belt"]["name"]    # What's printed on the device.

# HEART RATE SERVICE (HRS)
HRS = config["belt"]["heart_rate_service"]

# POLAR MEASUREMENT DATA CONTROL (PMDC)
PMDC = config["belt"]["pmd_control"]

# POLAR MEASUREMENT DATA - DATA (PMDD)
PMDD = config["belt"]["pmd_data"]

# BATTERY LEVEL
BATTERY = config["belt"]["battery"]

# DATA OUTPUT
ts = dt.now().strftime("%Y%m%d_%H%M")[2:]
ECG_FILE = DATA / f"ecg_{ts}.csv"
print(ECG_FILE)

# ECG SAMPLING DELTA TIMES
DT_ECG = 1 / config["recording"]["ecg_freq"]

# ECG PMD CONTROL POINTS (MEASUREMENT TYPE: 0x00)

ECG_START = bytearray([
	0x02, 0x00,					# command: start stream,  measurement type: ECG
	0x00, 0x01, 0x82, 0x00,		# setting: sample rate, 1 value, 130 Hz (= 0x82), 0 (Little endian!!!)
	0x01, 0x01, 0x0E, 0x00		# setting: resolution, 1 value, 14 bit (= 0x0E), 0
])

ECG_STOP = bytearray([0x03, 0x00]) # command: stop, measurement tpye: ECG

##############
# CONNECTING #
##############
   
print("Connecting. This may take up to 10 seconds")

def handle_ecg_packet(sender, data):
    print(f"PMD: {data.hex()}")

async def wait_for_space():
    while True:
        key = await asyncio.to_thread(msvcrt.getwch)
        if key == " ":
            return

async def main():
    start = time.perf_counter()

    # Create a blank csv file with col headers only.
    with open(ECG_FILE, "w", newline="") as f:
        ecg_writer = csv.writer(f)
        ecg_writer.writerow(["timestamp", "ecg"])

    async with BleakClient(BELT) as client:
        print(f"Connected to {belt_human_readable}.")

        # Check battery level
        battery_level = await client.read_gatt_char(BATTERY)
        print(f"Battery level: {battery_level[0]}%.")

        # Listen to incoming ECG
        print("Start listening to ECG")
        await client.start_notify(PMDD, handle_ecg_packet)

        print("To start streaming, press space. Press space again to stop streaming.")

        # Tell H10 to start ECG streaming
        await wait_for_space()
        print("Start streaming")
        await client.write_gatt_char(PMDC, ECG_START, response=True)

        # Stop ECG streaming
        await wait_for_space()
        print("Stop ECG stream")
        await client.write_gatt_char(PMDC, ECG_STOP, response=True)

        # Stop listening
        print("stop listening")
        await client.stop_notify(PMDD)

        print("Done.")
    
    # Diagnostics only
    end = time.perf_counter() - start
    print(f"Main function ran for {end:.6f} seconds.")


if __name__ == "__main__":
	asyncio.run(main())