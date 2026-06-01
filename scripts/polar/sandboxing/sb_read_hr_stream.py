import asyncio
from bleak import BleakClient
import pandas as pd
import time

# Polar H10 device identifier on macOS (CoreBluetooth UUID)
DEVICE_ADDRESS = "FFDB0E1C-0262-9016-D154-4562DABCBE43"
HR_CHAR = "00002a37-0000-1000-8000-00805f9b34fb"
STREAM_SECONDS = 60


def parse_hr_measurement(data: bytearray) -> int:
    flags = data[0]
    is_uint16 = bool(flags & 0x01)
    if is_uint16:
        return int.from_bytes(data[1:3], byteorder="little", signed=False)
    return data[1]


async def main():
    t_values = []
    hr_values = []

    def handle_hr(sender, data):
        t = time.time()
        hr = parse_hr_measurement(data)
        t_values.append(t)
        hr_values.append(hr)
        print(f"t:{t}, HR:{hr} bpm")

    async with BleakClient(DEVICE_ADDRESS) as client:
        print("Connected")

        await client.start_notify(HR_CHAR, handle_hr)

        print("Receiving heart rate... (Ctrl+C to stop)")
        await asyncio.sleep(STREAM_SECONDS)

        await client.stop_notify(HR_CHAR)

    hr_df = pd.DataFrame({"timestamp": t_values, "hr": hr_values})
    hr_df.to_csv("hrtest.csv", index=False)
    print("\nDataFrame preview:")
    print(hr_df.head())
    print(f"\nCollected {len(hr_df)} HR samples")
    print("Saved CSV: hrtest.csv")
    return hr_df



if __name__ == "__main__":
    asyncio.run(main())