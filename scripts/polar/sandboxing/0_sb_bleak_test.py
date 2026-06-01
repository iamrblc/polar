import asyncio
from bleak import BleakScanner


def format_bytes(data: bytes) -> str:
    return data.hex(" ") if data else ""


async def main():
    # return_adv=True exposes advertisement payload details beyond just address/name
    results = await BleakScanner.discover(timeout=8.0, return_adv=True)

    if not results:
        print("No BLE devices found.")
        return

    print(f"Found {len(results)} BLE device(s).\\n")

    for address, (device, adv) in results.items():
        display_name = adv.local_name or device.name or "<no name in advertisement>"

        print(f"Address:     {address}")
        print(f"Name:        {display_name}")
        print(f"RSSI:        {adv.rssi} dBm")

        if adv.service_uuids:
            print("Service UUIDs:")
            for uuid in adv.service_uuids:
                marker = "  [Heart Rate Service]" if uuid.lower() == "0000180d-0000-1000-8000-00805f9b34fb" else ""
                print(f"  - {uuid}{marker}")

        if adv.manufacturer_data:
            print("Manufacturer data:")
            for company_id, payload in adv.manufacturer_data.items():
                print(f"  - company_id=0x{company_id:04X}, data={format_bytes(payload)}")

        if adv.service_data:
            print("Service data:")
            for uuid, payload in adv.service_data.items():
                print(f"  - {uuid}: {format_bytes(payload)}")

        if adv.tx_power is not None:
            print(f"TX power:    {adv.tx_power} dBm")

        print("-" * 60)

asyncio.run(main())