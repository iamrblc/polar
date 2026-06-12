###################
# PACKAGE IMPORTS #
###################

# Generic stuff
import yaml					# To access config
from pathlib import Path	# To handle paths
import platform				# To assess OS
import time					# Time is money.
from datetime import datetime as dt
import pandas as pd 
import numpy as np
import neurokit2 as nk

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

# HEART RATE SERVICE (HRS) - not needed actually 
HRS = config["belt"]["heart_rate_service"]

# POLAR MEASUREMENT DATA CONTROL (PMDC)
PMDC = config["belt"]["pmd_control"]

# POLAR MEASUREMENT DATA - DATA (PMDD)
PMDD = config["belt"]["pmd_data"]

# BATTERY LEVEL
BATTERY = config["belt"]["battery"]

# ECG AND ACC DATAPOINT INTERVALS (DELTA TIME)
ECG_DT = 1 / config["recording"]["ecg_freq"]
ACC_DT = 1 / config["recording"]["acc_freq"]
ECG_DT_MS = ECG_DT * 1000
ACC_DT_MS = ACC_DT * 1000

# SUBJECT NAME
SUBJECT_NAME = config["experiment"]["subject_name"]

# ECG PMD CONTROL POINTS (MEASUREMENT TYPE: 0x00)

ECG_START = bytearray([
	0x02, 0x00,					# command: start stream,  measurement type: ECG
	0x00, 0x01, 0x82, 0x00,		# setting: sample rate, 1 value, 130 Hz (= 0x82), 0 (Little endian!!!)
	0x01, 0x01, 0x0E, 0x00		# setting: resolution, 1 value, 14 bit (= 0x0E), 0
])

ECG_STOP = bytearray([0x03, 0x00]) # command: stop, measurement tpye: ECG

# ACC PMD CONTROL POINTS (MEASUREMENT TYPE: 0x00)

ACC_START = bytearray([
	0x02, 0x02,					# command: start stream,  measurement type: ACC
	0x00, 0x01, 0xC8, 0x00,		# setting: sample rate, 1 value, 200 Hz (= 0xC8), 0 (Little endian!!!)
	0x01, 0x01, 0x10, 0x00,		# setting: resolution, 1 value, 16 bit (= 0x10), 0
    0x02, 0x01, 0x08, 0x00      # range: 8G
])

ACC_STOP = bytearray([0x03, 0x02]) # command: stop, measurement tpye: ACC

ecg_data = []
acc_data = []
ecg_packet_id = 0
acc_packet_id = 0

##############
# CONNECTING #
##############


print("Connecting. This may take up to 10 seconds")

def handle_pmd_packet(sender, data):
    global ecg_packet_id, acc_packet_id

    pm_type = "ECG" if data[0] == 0 else "ACC"
    pm_time = int.from_bytes(data[1:9], "little") / 1_000_000
    payload = data[10:]

    print(f"{pm_type} @ {pm_time}")

    if data[0] == 0:  # ECG
        packet_id = ecg_packet_id
        ecg_packet_id += 1

        for sample_idx, i in enumerate(range(0, len(payload), 3)):
            sample = int.from_bytes(payload[i:i+3], "little", signed=True)

            ecg_data.append({
                "packet_id": packet_id,
                "device_time": pm_time,
                "host_time": dt.now().timestamp() * 1000,
                "ecg": sample
            })

            print(sample)

    elif data[0] == 2:  # ACC
        packet_id = acc_packet_id
        acc_packet_id += 1

        for sample_idx, i in enumerate(range(0, len(payload), 6)):
            x = int.from_bytes(payload[i:i+2], "little", signed=True)
            y = int.from_bytes(payload[i+2:i+4], "little", signed=True)
            z = int.from_bytes(payload[i+4:i+6], "little", signed=True)

            acc_data.append({
                "packet_id": packet_id,
                "device_time": pm_time,
                "host_time": dt.now().timestamp() * 1000,
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

        # Listen to incoming ECG
        print("Start listening to ECG")
        await client.start_notify(PMDD, handle_pmd_packet)

        await asyncio.to_thread(input, "Press Enter to start recording: ")

        # One shared local timestamp suffix for both output files
        suffix_time = dt.now().strftime("%y%m%d_%H%M")

        # Tell H10 to start streaming
        print("Start streaming")
        await client.write_gatt_char(PMDC, ECG_START, response=True)
        await client.write_gatt_char(PMDC, ACC_START, response=True)
        
        await asyncio.to_thread(input, "Press Enter to end recording: ")

        # Stop streaming
        print("Stop stream")
        await client.write_gatt_char(PMDC, ECG_STOP, response=True)
        await client.write_gatt_char(PMDC, ACC_STOP, response=True)
        
        # Stop listening
        print("stop listening")
        await client.stop_notify(PMDD)

        print("Done.")

        #####################################
        # CREATING DATAFRAMES AND CSV FILES #
        #####################################

        # ECG
        ecg_df = pd.DataFrame(ecg_data)
        ecg_df["sample_idx"] = ecg_df.groupby("packet_id").cumcount()
        ecg_packet_sizes = ecg_df.groupby("packet_id")["packet_id"].transform("size")
        ecg_df["sample_time"] = (
            ecg_df["device_time"]
            - ((ecg_packet_sizes - 1 - ecg_df["sample_idx"]) * ECG_DT_MS)
        )
        ecg_df["time_ms"] = ecg_df["sample_time"] - ecg_df["sample_time"].min()

        # Add R-peak detection
        _, info = nk.ecg_peaks(
            ecg_df["ecg"],
            sampling_rate = 130
        )
        rpeaks = info["ECG_R_Peaks"]
        ecg_df["r_peak"] = 0
        ecg_df.loc[rpeaks, "r_peak"] = 1

        ecg_df.to_csv(DATA / f"{SUBJECT_NAME}_ecg_{suffix_time}.csv", index=False)
        

        # ACC
        acc_df = pd.DataFrame(acc_data)
        acc_df["sample_idx"] = acc_df.groupby("packet_id").cumcount()
        acc_packet_sizes = acc_df.groupby("packet_id")["packet_id"].transform("size")
        acc_df["sample_time"] = (
            acc_df["device_time"]
            - ((acc_packet_sizes - 1 - acc_df["sample_idx"]) * ACC_DT_MS)
        )
        acc_df["time_ms"] = acc_df["sample_time"] - acc_df["sample_time"].min()
        
         # Calculate acceleration magnitude
        acc_df["acc_mag"] = np.sqrt(
            acc_df["x"]**2 +
            acc_df["y"]**2 +
            acc_df["z"]**2)
        
        acc_df.to_csv(DATA / f"{SUBJECT_NAME}_acc_{suffix_time}.csv", index=False)

        # UNIFIED RECORDING
        recording = pd.merge_asof(
            ecg_df,
            acc_df[["time_ms", "x", "y", "z", "acc_mag"]],
            on="time_ms",
            direction="nearest"
        )
        recording = recording[["time_ms", "ecg", "r_peak", "acc_mag"]]

        recording.to_csv(DATA / f"{SUBJECT_NAME}_recording_{suffix_time}.csv", index=False)
    
    # Diagnostics only
    end = time.perf_counter() - start
    
    print(f"Main function ran for {end:.6f} seconds.")

if __name__ == "__main__":
	asyncio.run(main()) 