'''
Get ECG and accelerometer data (ACC) from a Polar H10 HR belt.
Make sure the belt is on when running the code.

Notes

It currently runs smoothly only on Mac.
There are other OS dependent issues beyond the device access
differences (MAC-address vs. UUID). This will be handled later.

Currently it runs for a fix time. Later a start and stop listener will be built in.

There are 3 different timestamps are used:
time (s)      	= Starts from the beginning of the measurement. Calculated from the device timestamps.
device time (ns)= Polar's raw timestamps. It marks the !!!END!!! of the transmitted package.
wall time (s)   = Posix time (seconds from 1970-01-01). From the computer running the code. Useful for syncing later.

'''

###################
# PACKAGE IMPORTS #
###################

# Generic stuff
import csv					
import time						

# Task specific stuff
'''
BleakClient manages bluetooth connection and data transfer.
There was a recommendation for using asyncio for concurrent codes
in the bleak github repo. Instead of running parallel threads, it pauses tasks 
so it can do something else. You basically use it like this:
- start a task (main).
- pause (await) — hand control to the event loop.
- the event loop runs whatever else is ready (e.g. an incoming Bluetooth data callback).
- when the pause is over, the event loop hands control back to your task.
- rinse and repeat.
'''

import asyncio   				
from bleak import BleakClient  

##########
# SETUPS #
##########

'''
Note: This section will be organized to the config.yaml and utils.py later on to keep this script clean.

PMD stands for Polar Measurement Data (both accelerometer and ECG).
Unlike with Heart Rate Service that is standardized and can be 
accessed directly, you get the data from PMD_DATA service by sending instructions 
to the control service (PMD_CONTROL). 
'''

DEVICE_ADDRESS = "A0:9E:1A:E6:B0:5E"  # Access on Linux
#DEVICE_ADDRESS = "FFDB0E1C-0262-9016-D154-4562DABCBE43" # Access on Mac

PMD_CONTROL = "fb005c81-02e7-f387-1cad-8acd2d8df0c8"
PMD_DATA = "fb005c82-02e7-f387-1cad-8acd2d8df0c8"

STREAM_SECONDS = 30				# How long should be the measurement.

FS_ACC = 200					# ACC frequency can be 50/100/150/200 Hz. 
DT_ACC = 1 / FS_ACC				# Delta time (s) between two consecutive ACC samples.
FS_ECG = 130					# ECG is 130 Hz. Just to make things more complicated. :) 
DT_ECG = 1 / FS_ECG				# Same as DT_ACC, but for the ECG data. 

'''
Later output data will be joined. For testing purposes it's better to keep them separate.
'''
ACC_OUTPUT_FILE = "acc_data.csv"			
ECG_OUTPUT_FILE = "ecg_data.csv"

'''
Polar labels each incoming data packet with single byte identifiers. So when a
packet arrives, we need to check the first byte against these values to know if
we receivde ACC (0x02) / ECG data (0x00).
'''
ACC_MEASUREMENT_TYPE = 0x02
ECG_MEASUREMENT_TYPE = 0x00

'''
Short command messages sent to the device asking "what settings are you currently using?".
0x01 is the Polar command code for "get current settings", followed by the measurement type.
The device responds via PMD_CONTROL and we just print the response for inspection.
'''
ACC_GET_SETTINGS = bytearray([0x01, ACC_MEASUREMENT_TYPE])
ECG_GET_SETTINGS = bytearray([0x01, ECG_MEASUREMENT_TYPE])

'''
These are the "start streaming" commands sent to the device, packed as raw bytes.
Basically the config form before hitting the REC button. :)

Each byte group specifies one setting (sample rate, resolution, range, etc).
The structure follows the Polar PMD protocol: [command, type, setting_id, value_length, value_bytes...].

ACC_START: start (0x02) ACC stream (0x02), at 200 Hz, 16-bit resolution, ±8 g range.
ECG_START: start (0x02) ECG stream (0x00), at 130 Hz, 14-bit resolution.

See comments at respective lines.
'''

ACC_START = bytearray([
	0x02, 0x02,					# command: start stream (0x02),  measurement type: ACC (0x02)
	0x00, 0x01, 0xC8, 0x00,		# setting: sample rate  → 0x00C8 = 200 Hz
	0x01, 0x01, 0x10, 0x00,		# setting: resolution   → 0x0010 = 16 bit
	0x02, 0x01, 0x08, 0x00		# setting: range        → 0x0008 = ±8 g
])

ECG_START = bytearray([
	0x02, 0x00,					# command: start stream (0x02),  measurement type: ECG (0x00)
	0x00, 0x01, 0x82, 0x00,		# setting: sample rate  → 0x0082 = 130 Hz
	0x01, 0x01, 0x0E, 0x00		# setting: resolution   → 0x000E = 14 bit
])

ACC_STOP = bytearray([0x03, ACC_MEASUREMENT_TYPE])
ECG_STOP = bytearray([0x03, ECG_MEASUREMENT_TYPE])


async def main():
	# t0_device_* anchors the device clock to "time zero" of the measurement,
	# so all sample timestamps start at 0 s instead of some huge nanosecond value.
	t0_device_acc = None
	t0_device_ecg = None
	# Flag to avoid printing the same ECG format warning over and over.
	ecg_compat_warned = False

	# Temporary storage for the samples inside one incoming packet.
	acc_buffer = []
	ecg_buffer = []

	with (
		open(ACC_OUTPUT_FILE, "w", newline="") as acc_csv_file,
		open(ECG_OUTPUT_FILE, "w", newline="") as ecg_csv_file,
	):
		acc_writer = csv.writer(acc_csv_file)
		ecg_writer = csv.writer(ecg_csv_file)
		# Write the header row so the columns are labelled in the output files.
		acc_writer.writerow(["time", "t_wall", "t_device_ns", "x", "y", "z"])
		ecg_writer.writerow(["time", "t_wall", "t_device_ns", "ecg"])

		# Called automatically whenever the device sends a response on the control channel
		# (e.g. confirming it received a command). We just print it — useful for debugging.
		def handle_pmd_control(sender, data: bytearray):
			print("PMD control:", data.hex(" "))

		# Called automatically every time the device sends a new data packet over Bluetooth.
		# It figures out whether the packet is ACC or ECG data, decodes the raw bytes into
		# human-readable numbers, calculates proper timestamps, and writes each sample to CSV.
		def handle_pmd_data(sender, data: bytearray):
			nonlocal t0_device_acc, t0_device_ecg, acc_buffer, ecg_buffer, ecg_compat_warned
			t_wall = time.time()
			if len(data) < 10:
				return

			measurement_type = data[0]

			if measurement_type == ACC_MEASUREMENT_TYPE:
				ts_ns = int.from_bytes(data[1:9], byteorder="little", signed=False)
				frame_type = data[9]
				if frame_type != 0x01:
					print(f"Unsupported ACC frame type: {frame_type:#04x}")
					return

				acc_buffer.clear()
				offset = 10
				while offset + 6 <= len(data):
					x = int.from_bytes(data[offset:offset + 2], byteorder="little", signed=True)
					y = int.from_bytes(data[offset + 2:offset + 4], byteorder="little", signed=True)
					z = int.from_bytes(data[offset + 4:offset + 6], byteorder="little", signed=True)
					acc_buffer.append((x, y, z))
					offset += 6

				T = ts_ns / 1e9
				N = len(acc_buffer)
				if N == 0:
					return

				if t0_device_acc is None:
					t0_device_acc = T - (N - 1) * DT_ACC

				for i, (x, y, z) in enumerate(acc_buffer):
					t_sample = T - (N - 1 - i) * DT_ACC - t0_device_acc
					acc_writer.writerow([f"{t_sample:.6f}", f"{t_wall:.6f}", ts_ns, x, y, z])
					print(
						f"ACC t={t_sample:.6f}  t_wall={t_wall:.3f}  ts_ns={ts_ns}"
						f"  x={x:6d}  y={y:6d}  z={z:6d}"
					)
				acc_csv_file.flush()
				return

			if measurement_type == ECG_MEASUREMENT_TYPE:
				ts_ns = int.from_bytes(data[1:9], byteorder="little", signed=False)
				frame_type = data[9]
				if frame_type != 0x00:
					print(f"Unsupported ECG frame type: {frame_type:#04x}")
					return

				ecg_buffer.clear()
				payload = data[10:]

				if len(payload) % 3 == 0:
					offset = 0
					while offset + 3 <= len(payload):
						ecg = int.from_bytes(payload[offset:offset + 3], byteorder="little", signed=True)
						ecg_buffer.append(ecg)
						offset += 3
				elif len(payload) % 2 == 0:
					if not ecg_compat_warned:
						print("ECG payload is not 24-bit aligned, falling back to 16-bit parsing")
						ecg_compat_warned = True
					offset = 0
					while offset + 2 <= len(payload):
						ecg = int.from_bytes(payload[offset:offset + 2], byteorder="little", signed=True)
						ecg_buffer.append(ecg)
						offset += 2
				else:
					print(f"Unsupported ECG payload length: {len(payload)}")
					return

				T = ts_ns / 1e9				# T = packet timestamp in seconds 
				N = len(ecg_buffer)			
				if N == 0:
					return

				if t0_device_ecg is None:
					t0_device_ecg = T - (N - 1) * DT_ECG

				for i, ecg in enumerate(ecg_buffer):
					t_sample = T - (N - 1 - i) * DT_ECG - t0_device_ecg
					ecg_writer.writerow([f"{t_sample:.6f}", f"{t_wall:.6f}", ts_ns, ecg])
					print(f"ECG t={t_sample:.6f}  t_wall={t_wall:.3f}  ts_ns={ts_ns}  ecg={ecg:6d}")
				ecg_csv_file.flush()

		async with BleakClient(DEVICE_ADDRESS) as client:
			print("Connected")

			await client.start_notify(PMD_CONTROL, handle_pmd_control)
			await client.start_notify(PMD_DATA, handle_pmd_data)

			try:
				print("Resetting previous ACC/ECG streams (if any)...")
				try:
					await client.write_gatt_char(PMD_CONTROL, ACC_STOP, response=True)
				except Exception:
					pass
				try:
					await client.write_gatt_char(PMD_CONTROL, ECG_STOP, response=True)
				except Exception:
					pass
				await asyncio.sleep(0.3)

				print("Requesting ACC settings...")
				await client.write_gatt_char(PMD_CONTROL, ACC_GET_SETTINGS, response=True)
				await asyncio.sleep(1.0)

				print("Requesting ECG settings...")
				await client.write_gatt_char(PMD_CONTROL, ECG_GET_SETTINGS, response=True)
				await asyncio.sleep(1.0)

				print("Starting ACC stream...")
				await client.write_gatt_char(PMD_CONTROL, ACC_START, response=True)
				await asyncio.sleep(0.2)

				print("Starting ECG stream...")
				await client.write_gatt_char(PMD_CONTROL, ECG_START, response=True)

				await asyncio.sleep(STREAM_SECONDS)
			finally:
				print("Stopping ACC stream...")
				try:
					await client.write_gatt_char(PMD_CONTROL, ACC_STOP, response=True)
				except Exception:
					pass
				await asyncio.sleep(0.2)

				print("Stopping ECG stream...")
				try:
					await client.write_gatt_char(PMD_CONTROL, ECG_STOP, response=True)
				except Exception:
					pass

				await client.stop_notify(PMD_DATA)
				await client.stop_notify(PMD_CONTROL)

	print(f"Saved ACC to {ACC_OUTPUT_FILE}")
	print(f"Saved ECG to {ECG_OUTPUT_FILE}")


if __name__ == "__main__":
	asyncio.run(main())


