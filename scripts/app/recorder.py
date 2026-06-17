from __future__ import annotations

from dataclasses import asdict
from datetime import datetime as dt
from pathlib import Path

import pandas as pd

from polar_reader import ACCSample, ECGSample


class ECGRecorder:
    """Store ECG samples, reconstruct sample-level timestamps, and save CSV."""

    def __init__(self, ecg_freq_hz: int):
        self._ecg_dt_ms = 1000.0 / ecg_freq_hz
        self._rows: list[dict] = []

    def clear(self) -> None:
        self._rows.clear()

    def ingest(self, batch: list[ECGSample]) -> None:
        if not batch:
            return
        for sample in batch:
            self._rows.append(asdict(sample))

    def has_data(self) -> bool:
        return len(self._rows) > 0

    def save(self, data_dir: Path, subject_name: str, suffix: str) -> Path:
        data_dir.mkdir(parents=True, exist_ok=True)
        out_path = data_dir / f"{subject_name}_ecg_{suffix}.csv"

        if not self._rows:
            # Save an empty file with expected columns so downstream tools do not fail.
            pd.DataFrame(columns=["packet_id", "device_time_ms", "host_time_ms", "ecg", "sample_idx", "sample_time_ms", "time_ms"]).to_csv(out_path, index=False)
            return out_path

        df = pd.DataFrame(self._rows)
        df["sample_idx"] = df.groupby("packet_id").cumcount()
        packet_sizes = df.groupby("packet_id")["packet_id"].transform("size")
        df["sample_time_ms"] = (
            df["device_time_ms"]
            - ((packet_sizes - 1 - df["sample_idx"]) * self._ecg_dt_ms)
        )
        df["time_ms"] = df["sample_time_ms"] - df["sample_time_ms"].min()
        df.to_csv(out_path, index=False)
        return out_path


class ACCRecorder:
    """Store ACC samples, reconstruct sample-level timestamps, and save CSV."""

    def __init__(self, acc_freq_hz: int):
        self._acc_dt_ms = 1000.0 / acc_freq_hz
        self._rows: list[dict] = []

    def clear(self) -> None:
        self._rows.clear()

    def ingest(self, batch: list[ACCSample]) -> None:
        if not batch:
            return
        for sample in batch:
            self._rows.append(asdict(sample))

    def save(self, data_dir: Path, subject_name: str, suffix: str) -> Path:
        data_dir.mkdir(parents=True, exist_ok=True)
        out_path = data_dir / f"{subject_name}_acc_{suffix}.csv"

        if not self._rows:
            pd.DataFrame(
                columns=[
                    "packet_id",
                    "device_time_ms",
                    "host_time_ms",
                    "x",
                    "y",
                    "z",
                    "sample_idx",
                    "sample_time_ms",
                    "time_ms",
                ]
            ).to_csv(out_path, index=False)
            return out_path

        df = pd.DataFrame(self._rows)
        df["sample_idx"] = df.groupby("packet_id").cumcount()
        packet_sizes = df.groupby("packet_id")["packet_id"].transform("size")
        df["sample_time_ms"] = (
            df["device_time_ms"]
            - ((packet_sizes - 1 - df["sample_idx"]) * self._acc_dt_ms)
        )
        df["time_ms"] = df["sample_time_ms"] - df["sample_time_ms"].min()
        df.to_csv(out_path, index=False)
        return out_path


def session_suffix() -> str:
    return dt.now().strftime("%y%m%d_%H%M")
