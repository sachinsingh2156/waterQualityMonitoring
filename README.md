# AquaSense — Live Water Monitoring

Python FastAPI dashboard for tank **water level**, **turbidity**, and **temperature**. Every value on the dashboard comes from the live Arduino serial stream only.

```
Arduino (JSON over Serial)
        │
        ▼
 pyserial bridge  ──publish──►  In-memory Pub/Sub
                                      │
                                subscribe / fan-out
                                      │
                                      ▼
                           WebSocket hub  (/ws)
                                      │
                                      ▼
                        AquaSense light dashboard
```

## Topics

| Topic | Publisher | Payload |
| --- | --- | --- |
| `sensors/water/data` | Serial bridge (Arduino only) | Temperature, turbidity, water level |
| `sensors/water/status` | Serial bridge | Connection mode & health |
| `system/events` | Server | Lifecycle events |

## Setup

```bash
cd water-sensors
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run with Arduino Uno

1. Flash [`arduino/water_monitor.ino`](arduino/water_monitor.ino).
2. Close Arduino Serial Monitor (only one process can use the port).
3. Start the server:

```bash
export SERIAL_PORT=/dev/cu.usbserial-1410   # your port
export BAUD_RATE=9600
python -m app.main
```

Or with uvicorn:

```bash
SERIAL_PORT=/dev/cu.usbserial-1410 uvicorn app.main:app --host 0.0.0.0 --port 3001
```

Open [http://localhost:3001](http://localhost:3001).

If the Arduino is disconnected, the dashboard stays empty until real serial readings arrive.

## API

- `GET /api/health`
- `GET /api/latest`
- `WS /ws` — frames `{ "type": "message", "topic": "...", "payload": {...} }`

## Pin map

| Sensor | Pin |
| --- | --- |
| Turbidity | `A0` |
| DS18B20 | `A1` |
| HC-SR04 TRIG | `2` |
| HC-SR04 ECHO | `3` |
