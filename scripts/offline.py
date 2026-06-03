import yaml
from pathlib import Path
import platform
import asyncio
from bleak import BleakClient

# Config data are stored in config.yaml
configpath = Path("/home/rblc/create/elte/polar/scripts/config.yaml")
with open (configpath, "r") as f:
        config = yaml.safe_load(f)

# BELT
'''
NOTE
Mac uses UUID, while Linux uses MAC address for the same task. So check the OS first.
Linux is called Linux. Windows is called Windows. Mac is called... wait for it... Darwin
'''
os = platform.system()
BELT = config["belt"]["uuid"] if os == "Darwin" else config["belt"]["mac_address"]
belt_human_readable = config["belt"]["name"]
# HEART RATE SERVICE (HRS)
HRS = config["belt"]["heart_rate_service"]

# POLAR MEASUREMENT DATA CONTROL (PMDC)
PMDC = config["belt"]["pmd_control"]

# POLAR MEASUREMENT DATA - DATA (PMDD)
PMDD = config["belt"]["pmd_data"]

ACC_MEASUREMENT_TYPE = 0x02
ECG_MEASUREMENT_TYPE = 0x00

ACC_GET_SETTINGS = bytearray([0x01, ACC_MEASUREMENT_TYPE])
ECG_GET_SETTINGS = bytearray([0x01, ECG_MEASUREMENT_TYPE])

def handle_pmd_control(sender, data):
    print("PMD CONTROL:", data.hex(" "))

async def main():

    async with BleakClient(BELT) as client:

        print(f"Connected to {belt_human_readable}")

        await client.start_notify(PMDC, handle_pmd_control)

        print("Requesting ACC settings...")
        await client.write_gatt_char(
            PMDC,
            ACC_GET_SETTINGS,
            response=True
        )


asyncio.run(main())