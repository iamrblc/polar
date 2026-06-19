from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

from polar_reader import ACCSample, AsyncRunner, ECGSample, PolarReader
from recorder import ACCRecorder, ECGRecorder, initialize_session_files, save_recording, session_suffix
from constants import BELTS, POLAR


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "recordings"


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
        
        self._subject_name = ""
        self._ecg_fs = POLAR["ECG_FREQ"]
        self._acc_fs = POLAR["ACC_FREQ"]

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

        self._reader = None

        self._recorder = ECGRecorder(ecg_freq_hz=self._ecg_fs)
        self._acc_recorder = ACCRecorder(acc_freq_hz=self._acc_fs)
        self._is_recording = False
        self._is_connected = False
        self._current_suffix = ""

        self._ecg_path = None
        self._acc_path = None
        self._recording_path = None

        self._flush_timer = QtCore.QTimer(self)
        self._flush_timer.setInterval(5000)
        self._flush_timer.timeout.connect(self._flush_recording_buffers)

        self._plot_samples = self._plot_window_sec * self._ecg_fs
        self._ring = np.zeros(self._plot_samples, dtype=np.float64)
        self._ring_count = 0
        self._ring_head = 0

        self._build_ui()
        self._set_disconnected_state()

    def _build_ui(self) -> None:
        container = QtWidgets.QWidget(self)
        self.setCentralWidget(container)
        layout = QtWidgets.QVBoxLayout(container)

        controls = QtWidgets.QHBoxLayout()
        self.belt_combo = QtWidgets.QComboBox()

        for belt_id, belt in BELTS.items():
            self.belt_combo.addItem(belt["name"], belt_id)

        self.subject_edit = QtWidgets.QLineEdit()
        self.subject_edit.setMinimumWidth(200)
        self.subject_edit.setPlaceholderText("subject_name")

        self.connect_btn = QtWidgets.QPushButton("Connect")

        controls.addWidget(self.belt_combo)
        controls.addWidget(self.subject_edit)
        controls.addWidget(self.connect_btn)

        self.start_btn = QtWidgets.QPushButton("Start")
        self.stop_btn = QtWidgets.QPushButton("Stop")
        self.status_lbl = QtWidgets.QLabel("Disconnected")
        self.battery_lbl = QtWidgets.QLabel("Battery level: -- %")
        self.status_lbl.setMinimumWidth(360)
        self.battery_lbl.setMinimumWidth(180)

        self.start_btn.clicked.connect(self._start_clicked)
        self.stop_btn.clicked.connect(self._stop_clicked)

        self.connect_btn.clicked.connect(self._connect_clicked)


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

    def _set_disconnected_state(self) -> None:
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)

    def _set_ready_state(self) -> None:
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def _set_recording_state(self) -> None:
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

    def _set_status(self, text: str) -> None:
        self.status_lbl.setText(text)
        if text == "Connected":
            self._is_connected = True
            self._set_ready_state()
            self.connect_btn.setEnabled(False)
            self.connect_btn.setText("Connected")
            self.status_lbl.setText("Connected (Ready)")

    def _set_battery(self, level: int) -> None:
        self.battery_lbl.setText(f"Battery level: {level} %")

    def _on_error(self, text: str) -> None:
        self._set_status(f"Error: {text}")
        self._is_recording = False
        if not self._is_connected:
            self._set_disconnected_state()
        else:
            self._set_ready_state()

    def _connect_clicked(self) -> None:
        belt_id = self.belt_combo.currentData()

        self._subject_name = self.subject_edit.text().strip() or "test"

        belt = BELTS[belt_id]
        self._reader = PolarReader(belt, POLAR)

        self._reader.on_status = self._signals.status.emit
        self._reader.on_error = self._signals.error.emit
        self._reader.on_battery = self._signals.battery.emit
        self._reader.on_ecg_batch = self._signals.ecg_batch.emit
        self._reader.on_acc_batch = self._signals.acc_batch.emit

        self._runner.submit(self._connect_pipeline())

    def _start_clicked(self) -> None:
        if self._is_recording or not self._is_connected:
            return

        self._recorder.clear()
        self._acc_recorder.clear()
        self._current_suffix = session_suffix()
        
        self._ecg_path, self._acc_path, self._recording_path = initialize_session_files(
            DATA_DIR,
            self._subject_name,
            self._current_suffix,
        )

        # This might not flash, as it's getting overwritten immediately.
        self._set_status(
            f"Session files created: {self._ecg_path.name}, {self._acc_path.name}, {self._recording_path.name}"
            )

        self._ring.fill(0.0)
        self._ring_head = 0
        self._ring_count = 0
        self.curve.setData([], [])

        self._is_recording = True
        self._set_recording_state()
        self._set_status("Recording")
        self._flush_timer.start()
        self._runner.submit(self._start_pipeline())

    def _stop_clicked(self) -> None:
        if not self._is_recording:
            return

        self._set_status("Stopping...")
        self.stop_btn.setEnabled(False)
        self._runner.submit(self._stop_pipeline())

    async def _start_pipeline(self):
        await self._reader.start_stream(ecg=True, acc=True)

    async def _stop_pipeline(self):
        await self._reader.stop_stream(ecg=True, acc=True)
        self._signals.reader_stopped.emit()

    async def _connect_pipeline(self):
        if self._reader is None:
            return
        await self._reader.connect()

    def _on_reader_stopped(self) -> None:
        self._flush_timer.stop()
        self._flush_recording_buffers()

        ecg_path, acc_path, recording_path = save_recording(
            DATA_DIR,
            self._subject_name,
            self._current_suffix,
            self._recorder,
            self._acc_recorder,
        )

        self._set_status(
            f"Saved: {ecg_path.name}, {acc_path.name}, {recording_path.name}"
        )

        self._is_recording = False
        self._set_ready_state()

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

    def _flush_recording_buffers(self) -> None:
        if not self._is_recording:
            return

        if self._ecg_path is not None:
            self._recorder.flush_buffer(self._ecg_path)

        if self._acc_path is not None:
            self._acc_recorder.flush_buffer(self._acc_path)


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
