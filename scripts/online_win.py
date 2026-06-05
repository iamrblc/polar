###################
# PACKAGE IMPORTS #
###################

# Generic stuff
import yaml					# To access config
from pathlib import Path	# To handle paths
import platform				# To assess OS
import csv					# To create csv output				
import time					# Time is money. 

# Communication with the device
from bleak import BleakClient # For bluetooth connection
import asyncio


ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CONFIG = ROOT / "scripts" / "config.yaml"

with open (CONFIG, "r") as f:
    config = yaml.safe_load(f)

os = platform.system()
BELT = config["belt"]["uuid"] if os == "Darwin" else config["belt"]["mac_address"]
belt_human_readable = config["belt"]["name"]
# HEART RATE SERVICE (HRS)
HRS = config["belt"]["heart_rate_service"]

# POLAR MEASUREMENT DATA CONTROL (PMDC)
PMDC = config["belt"]["pmd_control"]

# POLAR MEASUREMENT DATA - DATA (PMDD)
PMDD = config["belt"]["pmd_data"]

print("Connecting. This may take up to 30 seconds")

async def main():
    start = time.perf_counter()
    async with BleakClient(BELT) as client:
        print(f"Connected to {belt_human_readable}.")
    end = time.perf_counter() - start
    print(f"It took {end:.6f} seconds.")



if __name__ == "__main__":
	asyncio.run(main())