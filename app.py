from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pyqtgraph as pg
import yaml
from PySide6 import QtCore, QtWidgets

from polar_reader import ACCSample, AsyncRunner, ECGSample, PolarReader
from recorder import ACCRecorder, ECGRecorder, session_suffix


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "scripts" / "config.yaml"
DATA_DIR = ROOT / "data"


class UiSignals(QtCore.QObject):
    status = QtCore.Signal(str)
    error = QtCore.Signal(str)
    battery = QtCore.Signal(int)
    ecg_batch = QtCore.Signal(object)
    acc_batch = QtCore.Signal(object)
    reader_stopped = QtCore.Signal()


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Polar ECG Recorder")
        self.resize(1000, 620)

        with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
            config = yaml.safe_load(handle)

        self._subject_name = config["experiment"]["subject_name"] or "test"
        self._ecg_fs = int(config["recording"]["ecg_freq"])
        self._acc_fs = int(config["recording"]["acc_freq"])
        self._plot_window_sec = 5

        self._signals = UiSignals()
        self._signals.status.connect(self._set_status)
        self._signals.error.connect(self._on_error)
        self._signals.battery.connect(self._set_battery)
        self._signals.ecg_batch.connect(self._on_ecg_batch)
        self._signals.acc_batch.connect(self._on_acc_batch)
        self._signals.reader_stopped.connect(self._on_reader_stopped)

        self._runner = AsyncRunner()
        self._runner.start()

        self._reader = PolarReader(CONFIG_PATH)
        self._reader.on_status = self._signals.status.emit
        self._reader.on_error = self._signals.error.emit
        self._reader.on_battery = self._signals.battery.emit
        self._reader.on_ecg_batch = self._signals.ecg_batch.emit
        self._reader.on_acc_batch = self._signals.acc_batch.emit

        self._recorder = ECGRecorder(ecg_freq_hz=self._ecg_fs)
        self._acc_recorder = ACCRecorder(acc_freq_hz=self._acc_fs)
        self._is_recording = False
        self._current_suffix = ""

        self._plot_samples = self._plot_window_sec * self._ecg_fs
        self._ring = np.zeros(self._plot_samples, dtype=np.float64)
        self._ring_count = 0
        self._ring_head = 0

        self._build_ui()
        self._set_idle_state()

    def _build_ui(self) -> None:
        container = QtWidgets.QWidget(self)
        self.setCentralWidget(container)
        layout = QtWidgets.QVBoxLayout(container)

        controls = QtWidgets.QHBoxLayout()
        self.start_btn = QtWidgets.QPushButton("Start")
        self.stop_btn = QtWidgets.QPushButton("Stop")
        self.status_lbl = QtWidgets.QLabel("Disconnected")
        self.battery_lbl = QtWidgets.QLabel("Battery level: -- %")
        self.status_lbl.setMinimumWidth(360)
        self.battery_lbl.setMinimumWidth(180)

        self.start_btn.clicked.connect(self._start_clicked)
        self.stop_btn.clicked.connect(self._stop_clicked)

        controls.addWidget(self.start_btn)
        controls.addWidget(self.stop_btn)
        controls.addWidget(self.status_lbl)
        controls.addWidget(self.battery_lbl)
        controls.addStretch(1)
        layout.addLayout(controls)

        pg.setConfigOptions(antialias=True)
        self.plot = pg.PlotWidget(title="Live ECG")
        self.plot.setLabel("left", "ECG")
        self.plot.setLabel("bottom", "Time", units="s")
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.curve = self.plot.plot(pen=pg.mkPen(color=(45, 140, 240), width=1.8))
        layout.addWidget(self.plot, stretch=1)

    def _set_idle_state(self) -> None:
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def _set_recording_state(self) -> None:
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

    def _set_status(self, text: str) -> None:
        self.status_lbl.setText(text)

    def _set_battery(self, level: int) -> None:
        self.battery_lbl.setText(f"Battery level: {level} %")

    def _on_error(self, text: str) -> None:
        self._set_status(f"Error: {text}")
        self._is_recording = False
        self._set_idle_state()

    def _start_clicked(self) -> None:
        if self._is_recording:
            return

        self._recorder.clear()
        self._acc_recorder.clear()
        self._current_suffix = session_suffix()
        self._ring.fill(0.0)
        self._ring_head = 0
        self._ring_count = 0
        self.curve.setData([], [])

        self._is_recording = True
        self._set_recording_state()
        self._set_status("Connecting...")
        self._runner.submit(self._start_pipeline())

    def _stop_clicked(self) -> None:
        if not self._is_recording:
            return

        self._set_status("Stopping...")
        self.stop_btn.setEnabled(False)
        self._runner.submit(self._stop_pipeline())

    async def _start_pipeline(self):
        await self._reader.connect()
        await self._reader.start_stream(ecg=True, acc=True)

    async def _stop_pipeline(self):
        await self._reader.stop_stream(ecg=True, acc=True)
        await self._reader.disconnect()
        self._signals.reader_stopped.emit()

    def _on_reader_stopped(self) -> None:
        ecg_path = self._recorder.save(DATA_DIR, self._subject_name, self._current_suffix)
        acc_path = self._acc_recorder.save(DATA_DIR, self._subject_name, self._current_suffix)
        self._set_status(f"Saved: {ecg_path.name}, {acc_path.name}")
        self._is_recording = False
        self._set_idle_state()

    def _on_ecg_batch(self, batch: list[ECGSample]) -> None:
        if not self._is_recording:
            return

        self._recorder.ingest(batch)

        for sample in batch:
            self._ring[self._ring_head] = float(sample.ecg)
            self._ring_head = (self._ring_head + 1) % self._plot_samples
            self._ring_count = min(self._ring_count + 1, self._plot_samples)

        y = self._ordered_ring_view()
        if y.size == 0:
            return

        x = np.linspace(-y.size / self._ecg_fs, 0.0, num=y.size)
        self.curve.setData(x, y)

    def _on_acc_batch(self, batch: list[ACCSample]) -> None:
        if not self._is_recording:
            return
        self._acc_recorder.ingest(batch)

    def _ordered_ring_view(self) -> np.ndarray:
        if self._ring_count == 0:
            return np.array([], dtype=np.float64)

        if self._ring_count < self._plot_samples:
            return self._ring[: self._ring_count]

        return np.concatenate((self._ring[self._ring_head :], self._ring[: self._ring_head]))

    def closeEvent(self, event):
        if self._is_recording:
            self._runner.submit(self._reader.stop_stream(ecg=True, acc=True))
            self._runner.submit(self._reader.disconnect())
        self._runner.shutdown()
        event.accept()


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
