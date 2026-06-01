import asyncio
from bleak import BleakClient, BleakScanner


# This is for Mac for sure! I don't know if it works on Linux/Win or not
# Decathlon Dual HR belt
# DEVICE_ADDRESS = "C6B63DB5-8133-9F77-B6F2-3E42450FA4D2"
# HEART_RATE_SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"

# Polar 10 - one of them
DEVICE_ADDRESS = "A0:9E:1A:E6:B0:5E"
HEART_RATE_SERVICE_UUID =  "0000180d-0000-1000-8000-00805f9b34fb"

async def main() -> None:
	print(f"Looking for device {DEVICE_ADDRESS}...")
	device = await BleakScanner.find_device_by_address(DEVICE_ADDRESS, timeout=10.0)
	if device is None:
		print("Device not found. Make sure the belt is awake and advertising.")
		return

	print(f"Found: {device.name} ({device.address})")
	print("Connecting...")

	async with BleakClient(device) as client:
		print(f"Connected: {client.is_connected}")

		if hasattr(client, "get_services"):
			services = await client.get_services()
		else:
			services = client.services

		if services is None:
			print("No services discovered.")
			return

		service_list = list(services)
		print(f"Service count: {len(service_list)}")

		has_hr_service = any(s.uuid.lower() == HEART_RATE_SERVICE_UUID for s in service_list)
		print(f"Heart Rate service present: {has_hr_service}")

		print("\nGATT services and characteristics:")
		for service in service_list:
			print(f"[Service] {service.uuid}")
			for char in service.characteristics:
				props = ", ".join(char.properties)
				print(f"  - {char.uuid} ({props})")

	print("Disconnected.")


if __name__ == "__main__":
	asyncio.run(main())
