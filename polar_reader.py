from __future__ import annotations

import asyncio
import platform
from dataclasses import dataclass
from datetime import datetime as dt
from pathlib import Path
from typing import Callable

import yaml
from bleak import BleakClient


@dataclass(slots=True)
class ECGSample:
    packet_id: int
    device_time_ms: float
    host_time_ms: float
    ecg: int


@dataclass(slots=True)
class ACCSample:
    packet_id: int
    device_time_ms: float
    host_time_ms: float
    x: int
    y: int
    z: int


class PolarReader:
    """Read ECG/ACC packets from Polar H10 and emit parsed sample batches."""

    ECG_START = bytearray(
        [
            0x02,
            0x00,
            0x00,
            0x01,
            0x82,
            0x00,
            0x01,
            0x01,
            0x0E,
            0x00,
        ]
    )
    ECG_STOP = bytearray([0x03, 0x00])

    ACC_START = bytearray(
        [
            0x02,
            0x02,
            0x00,
            0x01,
            0xC8,
            0x00,
            0x01,
            0x01,
            0x10,
            0x00,
            0x02,
            0x01,
            0x08,
            0x00,
        ]
    )
    ACC_STOP = bytearray([0x03, 0x02])

    def __init__(self, config_path: Path):
        with open(config_path, "r", encoding="utf-8") as handle:
            config = yaml.safe_load(handle)

        self._belt_name = config["belt"]["name"]
        os_name = platform.system()
        self._belt_address = (
            config["belt"]["uuid"] if os_name == "Darwin" else config["belt"]["mac_address"]
        )
        self._pmd_control = config["belt"]["pmd_control"]
        self._pmd_data = config["belt"]["pmd_data"]
        self._battery = config["belt"]["battery"]

        self._client: BleakClient | None = None
        self._is_streaming = False
        self._ecg_packet_id = 0
        self._acc_packet_id = 0

        self.on_status: Callable[[str], None] = lambda _text: None
        self.on_error: Callable[[str], None] = lambda _text: None
        self.on_battery: Callable[[int], None] = lambda _level: None
        self.on_ecg_batch: Callable[[list[ECGSample]], None] = lambda _batch: None
        self.on_acc_batch: Callable[[list[ACCSample]], None] = lambda _batch: None

    async def connect(self) -> None:
        if self._client and self._client.is_connected:
            return

        self.on_status(f"Connecting to {self._belt_name}...")
        try:
            client = BleakClient(self._belt_address)
            await client.connect()
            battery = await client.read_gatt_char(self._battery)
            self.on_battery(int(battery[0]))
            self.on_status("Connected")
            self._client = client
        except Exception as exc:
            self.on_error(f"Connection failed: {exc}")

    async def disconnect(self) -> None:
        client = self._client
        if not client:
            return

        try:
            if client.is_connected:
                await client.disconnect()
                self.on_status("Disconnected")
        except Exception as exc:
            self.on_error(f"Disconnect failed: {exc}")
        finally:
            self._client = None
            self._is_streaming = False

    async def start_stream(self, ecg: bool = True, acc: bool = False) -> None:
        client = self._client
        if not client or not client.is_connected:
            self.on_error("Cannot start stream: device is not connected")
            return

        if self._is_streaming:
            return

        try:
            await client.start_notify(self._pmd_data, self._handle_pmd_packet)
            if ecg:
                await client.write_gatt_char(self._pmd_control, self.ECG_START, response=True)
            if acc:
                await client.write_gatt_char(self._pmd_control, self.ACC_START, response=True)
            self._is_streaming = True
            self.on_status("Recording")
        except Exception as exc:
            self.on_error(f"Start stream failed: {exc}")

    async def stop_stream(self, ecg: bool = True, acc: bool = False) -> None:
        client = self._client
        if not client or not client.is_connected:
            return

        if not self._is_streaming:
            return

        try:
            if ecg:
                await client.write_gatt_char(self._pmd_control, self.ECG_STOP, response=True)
            if acc:
                await client.write_gatt_char(self._pmd_control, self.ACC_STOP, response=True)
            await client.stop_notify(self._pmd_data)
            self._is_streaming = False
            self.on_status("Stopped")
        except Exception as exc:
            self.on_error(f"Stop stream failed: {exc}")

    def _handle_pmd_packet(self, _sender: int, data: bytearray) -> None:
        if not data or len(data) < 10:
            return

        measurement_type = data[0]
        device_time_ms = int.from_bytes(data[1:9], "little") / 1_000_000
        payload = data[10:]
        host_time_ms = dt.now().timestamp() * 1000

        if measurement_type == 0x00:
            batch = self._parse_ecg(payload, device_time_ms, host_time_ms)
            if batch:
                self.on_ecg_batch(batch)
            return

        if measurement_type == 0x02:
            batch = self._parse_acc(payload, device_time_ms, host_time_ms)
            if batch:
                self.on_acc_batch(batch)

    def _parse_ecg(
        self, payload: bytearray, device_time_ms: float, host_time_ms: float
    ) -> list[ECGSample]:
        packet_id = self._ecg_packet_id
        self._ecg_packet_id += 1

        out: list[ECGSample] = []
        if len(payload) % 3 == 0:
            for idx in range(0, len(payload), 3):
                sample = int.from_bytes(payload[idx : idx + 3], "little", signed=True)
                out.append(
                    ECGSample(
                        packet_id=packet_id,
                        device_time_ms=device_time_ms,
                        host_time_ms=host_time_ms,
                        ecg=sample,
                    )
                )
        elif len(payload) % 2 == 0:
            # Compatibility fallback for payloads observed in older tests.
            for idx in range(0, len(payload), 2):
                sample = int.from_bytes(payload[idx : idx + 2], "little", signed=True)
                out.append(
                    ECGSample(
                        packet_id=packet_id,
                        device_time_ms=device_time_ms,
                        host_time_ms=host_time_ms,
                        ecg=sample,
                    )
                )
        else:
            self.on_error(f"Unsupported ECG payload length: {len(payload)}")

        return out

    def _parse_acc(
        self, payload: bytearray, device_time_ms: float, host_time_ms: float
    ) -> list[ACCSample]:
        packet_id = self._acc_packet_id
        self._acc_packet_id += 1

        out: list[ACCSample] = []
        for idx in range(0, len(payload), 6):
            if idx + 6 > len(payload):
                break
            x = int.from_bytes(payload[idx : idx + 2], "little", signed=True)
            y = int.from_bytes(payload[idx + 2 : idx + 4], "little", signed=True)
            z = int.from_bytes(payload[idx + 4 : idx + 6], "little", signed=True)
            out.append(
                ACCSample(
                    packet_id=packet_id,
                    device_time_ms=device_time_ms,
                    host_time_ms=host_time_ms,
                    x=x,
                    y=y,
                    z=z,
                )
            )
        return out


class AsyncRunner:
    """Own an asyncio loop in a background thread and run coroutines on it."""

    def __init__(self):
        self._loop = asyncio.new_event_loop()
        self._thread = None

    def start(self) -> None:
        import threading

        if self._thread and self._thread.is_alive():
            return

        def _run() -> None:
            asyncio.set_event_loop(self._loop)
            self._loop.run_forever()

        self._thread = threading.Thread(target=_run, name="polar-async-loop", daemon=True)
        self._thread.start()

    def submit(self, coro: asyncio.coroutines) -> None:
        if not self._thread or not self._thread.is_alive():
            self.start()
        asyncio.run_coroutine_threadsafe(coro, self._loop)

    def shutdown(self) -> None:
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
