from __future__ import annotations

from dataclasses import asdict
from datetime import datetime as dt
from pathlib import Path

import neurokit2 as nk
import numpy as np
import pandas as pd

from polar_reader import ACCSample, ECGSample


class ECGRecorder:
    def __init__(self, ecg_freq_hz: int):
        self._ecg_freq_hz = ecg_freq_hz
        self._ecg_dt_ms = 1000.0 / ecg_freq_hz
        self._rows: list[dict] = []

    def clear(self) -> None:
        self._rows.clear()

    def ingest(self, batch: list[ECGSample]) -> None:
        for sample in batch:
            self._rows.append(asdict(sample))

    def to_dataframe(self) -> pd.DataFrame:
        df = pd.DataFrame(self._rows)

        if df.empty:
            return pd.DataFrame(
                columns=[
                    "packet_id",
                    "device_time_ms",
                    "host_time_ms",
                    "ecg",
                    "sample_idx",
                    "sample_time_ms",
                    "time_ms",
                ]
            )

        df["sample_idx"] = df.groupby("packet_id").cumcount()
        packet_sizes = df.groupby("packet_id")["packet_id"].transform("size")

        df["sample_time_ms"] = (
            df["device_time_ms"]
            - ((packet_sizes - 1 - df["sample_idx"]) * self._ecg_dt_ms)
        )

        df["time_ms"] = df["sample_time_ms"] - df["sample_time_ms"].min()

        return df

    def save(self, data_dir: Path, subject_name: str, suffix: str) -> Path:
        data_dir.mkdir(parents=True, exist_ok=True)
        out_path = data_dir / f"{subject_name}_ecg_{suffix}.csv"

        df = self.to_dataframe()
        df.to_csv(out_path, index=False)

        return out_path


class ACCRecorder:
    def __init__(self, acc_freq_hz: int):
        self._acc_dt_ms = 1000.0 / acc_freq_hz
        self._rows: list[dict] = []

    def clear(self) -> None:
        self._rows.clear()

    def ingest(self, batch: list[ACCSample]) -> None:
        for sample in batch:
            self._rows.append(asdict(sample))

    def to_dataframe(self) -> pd.DataFrame:
        df = pd.DataFrame(self._rows)

        if df.empty:
            return pd.DataFrame(
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
            )

        df["sample_idx"] = df.groupby("packet_id").cumcount()
        packet_sizes = df.groupby("packet_id")["packet_id"].transform("size")

        df["sample_time_ms"] = (
            df["device_time_ms"]
            - ((packet_sizes - 1 - df["sample_idx"]) * self._acc_dt_ms)
        )

        df["time_ms"] = df["sample_time_ms"] - df["sample_time_ms"].min()

        return df

    def save(self, data_dir: Path, subject_name: str, suffix: str) -> Path:
        data_dir.mkdir(parents=True, exist_ok=True)
        out_path = data_dir / f"{subject_name}_acc_{suffix}.csv"

        df = self.to_dataframe()
        df.to_csv(out_path, index=False)

        return out_path


def save_recording(
    data_dir: Path,
    subject_name: str,
    suffix: str,
    ecg_recorder: ECGRecorder,
    acc_recorder: ACCRecorder,
) -> tuple[Path, Path, Path]:
    data_dir.mkdir(parents=True, exist_ok=True)

    ecg_df = ecg_recorder.to_dataframe()
    acc_df = acc_recorder.to_dataframe()

    ecg_path = data_dir / f"{subject_name}_ecg_{suffix}.csv"
    acc_path = data_dir / f"{subject_name}_acc_{suffix}.csv"
    recording_path = data_dir / f"{subject_name}_recording_{suffix}.csv"

    ecg_df.to_csv(ecg_path, index=False)
    acc_df.to_csv(acc_path, index=False)

    if ecg_df.empty:
        recording = pd.DataFrame(columns=["time_ms", "ecg", "r_peak", "acc_mag"])
        recording.to_csv(recording_path, index=False)
        return ecg_path, acc_path, recording_path

    _, info = nk.ecg_peaks(
        ecg_df["ecg"],
        sampling_rate=ecg_recorder._ecg_freq_hz,
    )

    ecg_for_recording = ecg_df[["time_ms", "ecg"]].copy()
    ecg_for_recording["r_peak"] = 0
    ecg_for_recording.loc[info["ECG_R_Peaks"], "r_peak"] = 1

    if acc_df.empty:
        ecg_for_recording["acc_mag"] = np.nan
        recording = ecg_for_recording[["time_ms", "ecg", "r_peak", "acc_mag"]]
    else:
        acc_for_recording = acc_df[["time_ms", "x", "y", "z"]].copy()
        acc_for_recording["acc_mag"] = np.sqrt(
            acc_for_recording["x"] ** 2
            + acc_for_recording["y"] ** 2
            + acc_for_recording["z"] ** 2
        )

        recording = pd.merge_asof(
            ecg_for_recording.sort_values("time_ms"),
            acc_for_recording[["time_ms", "acc_mag"]].sort_values("time_ms"),
            on="time_ms",
            direction="nearest",
        )

        recording = recording[["time_ms", "ecg", "r_peak", "acc_mag"]]

    recording.to_csv(recording_path, index=False)

    return ecg_path, acc_path, recording_path


def session_suffix() -> str:
    return dt.now().strftime("%y%m%d_%H%M")