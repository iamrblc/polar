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

# DATA OUTPUT
ts = dt.now().strftime("%Y%m%d_%H%M")[2:]
ECG_FILE = DATA / f"ecg_{ts}.csv"
print(ECG_FILE)

# ACC AND ECG SAMPLING DELTA TIMES
DT_ACC = 1 / config["recording"]["acc_freq"]
DT_ECG = 1 / config["recording"]["ecg_freq"]

# DATA STREAM DURATION
# For now. Later it will be user start/stop
STREAM_DUR = config["recording"]["stream_duration"]

print(DT_ACC, DT_ECG, STREAM_DUR)
exit()

##############
# CONNECTING #
##############

print("Connecting. This may take up to 30 seconds")

async def main():
    start = time.perf_counter()
    async with BleakClient(BELT) as client:
        print(f"Connected to {belt_human_readable}.")
    end = time.perf_counter() - start
    print(f"It took {end:.6f} seconds.")



if __name__ == "__main__":
	asyncio.run(main())