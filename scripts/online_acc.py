###################
# PACKAGE IMPORTS #
###################

# Generic stuff
import yaml					# To access config
from pathlib import Path	# To handle paths
import platform				# To assess OS
import time					# Time is money.
import pandas as pd 

# Communication with the device
from bleak import BleakClient # For bluetooth connection
import asyncio


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

# DATA STREAM DURATION
STREAM_DUR = config["recording"]["stream_duration"]

# ECG DATAPOINT INTERVALS (DELTA TIME)
ACC_DT = 1 / config["recording"]["acc_freq"]

# ECG PMD CONTROL POINTS (MEASUREMENT TYPE: 0x00)

ACC_START = bytearray([
	0x02, 0x02,					# command: start stream,  measurement type: ACC
	0x00, 0x01, 0xC8, 0x00,		# setting: sample rate, 1 value, 200 Hz (= 0xC8), 0 (Little endian!!!)
	0x01, 0x01, 0x10, 0x00,		# setting: resolution, 1 value, 16 bit (= 0x10), 0
    0x02, 0x01, 0x08, 0x00      # range: 8G
])

ACC_STOP = bytearray([0x03, 0x02]) # command: stop, measurement tpye: ACC

acc_data = []

##############
# CONNECTING #
##############


print("Connecting. This may take up to 10 seconds")

def handle_acc_packet(sender, data):
    pm_type = "ECG" if data[0] == 0 else "ACC"
    pm_time = int.from_bytes(data[1:9], "little") // 1_000_000
    payload = data[10:]

    print(f"{pm_type} @ {pm_time}")
    for sample_idx, i in enumerate(range(0, len(payload), 6)):
        x = int.from_bytes(payload[i:i+2], "little", signed=True)
        y = int.from_bytes(payload[i+2:i+4], "little", signed=True)
        z = int.from_bytes(payload[i+4:i+6], "little", signed=True)

        sample_time = int(pm_time + (sample_idx * ACC_DT * 1000))

        acc_data.append({
            "timestamp": sample_time,
            "x": x,
            "y": y,
            "z": z,
        })

        print(x, y, z)

async def main():
    start = time.perf_counter()

    async with BleakClient(BELT) as client:
        print(f"Connected to {belt_human_readable}.")

        # Check battery level
        battery_level = await client.read_gatt_char(BATTERY)
        print(f"Battery level: {battery_level[0]}%.")

        # Listen to incoming ACC
        print("Start listening to ACC")
        await client.start_notify(PMDD, handle_acc_packet)

        # Tell H10 to start ACC streaming
        print("Start streaming")
        await client.write_gatt_char(PMDC, ACC_START, response=True)

        # Keep stream alive for chosen duration
        print("Keep stream alive")
        await asyncio.sleep(STREAM_DUR)

        # Stop ACC streaming
        print("Stop ACC stream")
        await client.write_gatt_char(PMDC, ACC_STOP, response=True)

        # Stop listening
        print("stop listening")
        await client.stop_notify(PMDD)

        print("Done.")

        acc_df = pd.DataFrame(acc_data)
        acc_df.to_csv(DATA / "test_acc.csv", index=False)
    
    # Diagnostics only
    end = time.perf_counter() - start
    
    print(f"Main function ran for {end:.6f} seconds.")



if __name__ == "__main__":
	asyncio.run(main()) 