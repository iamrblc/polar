import asyncio
import csv
import time
from bleak import BleakClient

#DEVICE_ADDRESS = "A0:9E:1A:E6:B0:5E"
DEVICE_ADDRESS = "FFDB0E1C-0262-9016-D154-4562DABCBE43"

PMD_CONTROL = "fb005c81-02e7-f387-1cad-8acd2d8df0c8"
PMD_DATA    = "fb005c82-02e7-f387-1cad-8acd2d8df0c8"

STREAM_SECONDS = 5

FS = 130
DT = 1 / FS
OUTPUT_FILE = "ecg_data.csv"

# PMD measurement type for ECG is 0x00
ECG_MEASUREMENT_TYPE = 0x00

# Step 1: ask device which ECG settings it supports
ECG_GET_SETTINGS = bytearray([0x01, ECG_MEASUREMENT_TYPE])

# Step 2: start ECG with one concrete setting set.
#   op=0x02 (start)
#   type=0x00 (ECG)
#   sample rate = 0x0082 = 130 Hz
#   resolution  = 0x000E = 14 bit
ECG_START = bytearray([
    0x02, 0x00,
    0x00, 0x01, 0x82, 0x00,
    0x01, 0x01, 0x0E, 0x00
])

# Stop ECG stream
ECG_STOP = bytearray([0x03, ECG_MEASUREMENT_TYPE])


async def main():
    t0_device = None  # device time (s) of the very first sample, for anchoring

    with open(OUTPUT_FILE, "w", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["time", "t_wall", "t_device_ns", "ecg"])

        def handle_pmd_control(sender, data: bytearray):
            print("PMD control:", data.hex(" "))

        def handle_pmd_data(sender, data: bytearray):
            nonlocal t0_device
            t_wall = time.time()
            if data[0] != ECG_MEASUREMENT_TYPE:
                return

            # Bytes 1-8: device timestamp (uint64 LE, nanoseconds)
            # This marks the time of the LAST sample in the packet.
            ts_ns = int.from_bytes(data[1:9], byteorder='little', signed=False)

            # Byte 9: frame type (0x00 = raw uncompressed for ECG)
            frame_type = data[9]
            if frame_type != 0x00:
                print(f"Unsupported frame type: {frame_type:#04x}")
                return

            # Bytes 10+: ECG samples, 3 bytes each (int24 LE, single channel)
            samples = []
            offset = 10
            while offset + 3 <= len(data):
                ecg = int.from_bytes(data[offset:offset+3], byteorder='little', signed=True)
                samples.append(ecg)
                offset += 3

            T = ts_ns / 1e9  # device time of the last sample (seconds)
            N = len(samples)

            # Anchor t=0 to the first sample of the first packet
            if t0_device is None:
                t0_device = T - (N - 1) * DT

            for i, ecg in enumerate(samples):
                t_sample = T - (N - 1 - i) * DT - t0_device
                writer.writerow([f"{t_sample:.6f}", f"{t_wall:.6f}", ts_ns, ecg])
                print(f"t={t_sample:.6f}  t_wall={t_wall:.3f}  ts_ns={ts_ns}  ecg={ecg:6d}")

        async with BleakClient(DEVICE_ADDRESS) as client:
            print("Connected")

            await client.start_notify(PMD_CONTROL, handle_pmd_control)
            await client.start_notify(PMD_DATA, handle_pmd_data)

            print("Requesting ECG settings...")
            await client.write_gatt_char(PMD_CONTROL, ECG_GET_SETTINGS, response=True)
            await asyncio.sleep(1.0)

            print("Starting ECG stream...")
            await client.write_gatt_char(PMD_CONTROL, ECG_START, response=True)

            await asyncio.sleep(STREAM_SECONDS)

            print("Stopping ECG stream...")
            await client.write_gatt_char(PMD_CONTROL, ECG_STOP, response=True)

            await client.stop_notify(PMD_DATA)
            await client.stop_notify(PMD_CONTROL)

    print(f"Saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
