"""Read newline-delimited JSON from Arduino Serial and publish to pub/sub."""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import serial
from serial.tools import list_ports

from app.pubsub import TOPICS

if TYPE_CHECKING:
    from app.pubsub import PubSub


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _find_port(explicit: str | None) -> str | None:
    if explicit:
        return explicit

    ports = list(list_ports.comports())
    for port in ports:
        blob = f"{port.manufacturer or ''} {port.device} {port.description or ''}"
        if any(
            key in blob.lower()
            for key in ("arduino", "usbserial", "usbmodem", "ch340", "cp210", "ftdi")
        ):
            return port.device
    return ports[0].device if ports else None


def normalize_reading(data: dict) -> dict:
    temperature_c = data.get("temperatureC")
    if temperature_c is None and isinstance(data.get("temperature"), dict):
        temperature_c = data["temperature"].get("celsius")

    turbidity_index = data.get("turbidity", data.get("turbidityIndex"))
    if isinstance(turbidity_index, dict):
        turbidity_index = turbidity_index.get("index")

    turbidity_raw = data.get("turbidityRaw")
    if turbidity_raw is None and isinstance(data.get("turbidity"), dict):
        turbidity_raw = data["turbidity"].get("raw")

    # Recompute dirtiness from raw ADC when present so clear-water readings
    # (often ~900–1023) are not stuck at a clamped 0 on the dashboard.
    voltage = None
    if turbidity_raw is not None:
        try:
            raw_f = float(turbidity_raw)
            voltage = round(raw_f * (5.0 / 1023.0), 3)
            turbidity_index = int(round(100.0 - (raw_f / 1023.0) * 100.0))
            turbidity_index = max(0, min(100, turbidity_index))
        except (TypeError, ValueError):
            pass

    water_level_cm = data.get("waterLevelCm")
    if water_level_cm is None and isinstance(data.get("waterLevel"), dict):
        water_level_cm = data["waterLevel"].get("levelCm")

    tank_height = data.get("tankHeightCm")
    if tank_height is None and isinstance(data.get("waterLevel"), dict):
        tank_height = data["waterLevel"].get("tankHeightCm")

    status = data.get("waterStatus")
    if status is None and isinstance(data.get("turbidity"), dict):
        status = data["turbidity"].get("status")
    if turbidity_index is not None:
        if turbidity_index < 20:
            status = "CLEAR"
        elif turbidity_index < 50:
            status = "CLOUDY"
        else:
            status = "DIRTY"

    temp_connected = data.get("tempConnected")
    if temp_connected is None:
        temp_connected = temperature_c is not None

    distance_cm = data.get("distanceCm")
    if distance_cm is None and isinstance(data.get("waterLevel"), dict):
        distance_cm = data["waterLevel"].get("distanceCm")

    level_valid = data.get("levelValid")
    if level_valid is None:
        level_valid = water_level_cm is not None

    percentage = data.get("waterLevelPct")
    if (
        percentage is None
        and water_level_cm is not None
        and tank_height is not None
        and float(tank_height) != 0
    ):
        percentage = round((float(water_level_cm) / float(tank_height)) * 100.0, 1)

    fahrenheit = None
    if temperature_c is not None:
        fahrenheit = round((float(temperature_c) * 9 / 5) + 32, 2)

    return {
        "timestamp": _now(),
        "source": "arduino",
        "temperature": {
            "celsius": temperature_c,
            "fahrenheit": fahrenheit,
            "connected": bool(temp_connected),
        },
        "turbidity": {
            "raw": turbidity_raw,
            "voltage": voltage,
            "index": turbidity_index,
            "status": status,
        },
        "waterLevel": {
            "distanceCm": distance_cm,
            "levelCm": water_level_cm,
            "percentage": percentage,
            "tankHeightCm": tank_height,
            "valid": bool(level_valid),
        },
    }


class SerialBridge:
    def __init__(
        self,
        pubsub: PubSub,
        path: str | None = None,
        baud_rate: int = 9600,
    ) -> None:
        self.pubsub = pubsub
        self.path = path
        self.baud_rate = baud_rate
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._port: serial.Serial | None = None

    def start(self) -> None:
        resolved = _find_port(self.path)
        if not resolved:
            raise RuntimeError(
                "No serial port found. Connect the Arduino and set SERIAL_PORT "
                "(e.g. /dev/cu.usbserial-1410)."
            )

        self.path = resolved
        self._thread = threading.Thread(target=self._run, name="serial-bridge", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._port and self._port.is_open:
            try:
                self._port.close()
            except Exception:  # noqa: BLE001
                pass
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        assert self.path is not None
        try:
            self._port = serial.Serial(self.path, self.baud_rate, timeout=1)
        except Exception as exc:  # noqa: BLE001
            print(f"[serial] error: {exc}")
            self.pubsub.publish(
                TOPICS["SENSOR_STATUS"],
                {
                    "timestamp": _now(),
                    "connected": False,
                    "mode": "serial",
                    "message": str(exc),
                },
            )
            return

        print(f"[serial] connected to {self.path} @ {self.baud_rate}")
        self.pubsub.publish(
            TOPICS["SENSOR_STATUS"],
            {
                "timestamp": _now(),
                "connected": True,
                "mode": "serial",
                "port": self.path,
                "message": f"Listening on {self.path}",
            },
        )

        buffer = ""
        while not self._stop.is_set():
            try:
                chunk = self._port.read(self._port.in_waiting or 1)
                if not chunk:
                    time.sleep(0.02)
                    continue
                buffer += chunk.decode("utf-8", errors="ignore")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    self._handle_line(line.strip())
            except Exception as exc:  # noqa: BLE001
                if self._stop.is_set():
                    break
                print(f"[serial] read error: {exc}")
                self.pubsub.publish(
                    TOPICS["SENSOR_STATUS"],
                    {
                        "timestamp": _now(),
                        "connected": False,
                        "mode": "serial",
                        "message": str(exc),
                    },
                )
                time.sleep(1)

        self.pubsub.publish(
            TOPICS["SENSOR_STATUS"],
            {
                "timestamp": _now(),
                "connected": False,
                "mode": "serial",
                "message": "Serial port closed",
            },
        )

    def _handle_line(self, line: str) -> None:
        if not line.startswith("{"):
            return
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            print(f"[serial] bad JSON: {line[:120]} {exc}")
            return
        self.pubsub.publish(TOPICS["SENSOR_DATA"], normalize_reading(data))
