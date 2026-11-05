"""AquaSense FastAPI server — live Arduino serial → pub/sub → WebSocket."""

from __future__ import annotations

import argparse
import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.pubsub import TOPICS, PubSub
from app.serial_bridge import SerialBridge

ROOT = Path(__file__).resolve().parent
pubsub = PubSub()
_source: SerialBridge | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _start_source() -> None:
    """Connect only to the live Arduino serial stream."""
    global _source
    try:
        bridge = SerialBridge(
            pubsub,
            path=os.environ.get("SERIAL_PORT"),
            baud_rate=int(os.environ.get("BAUD_RATE", "9600")),
        )
        bridge.start()
        _source = bridge
    except Exception as exc:  # noqa: BLE001
        print(f"[boot] serial unavailable: {exc}")
        pubsub.publish(
            TOPICS["SENSOR_STATUS"],
            {
                "timestamp": _now(),
                "connected": False,
                "mode": "serial",
                "message": f"Waiting for Arduino: {exc}",
            },
        )
        _source = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _start_source()
    pubsub.publish(
        TOPICS["SYSTEM"],
        {
            "timestamp": _now(),
            "event": "server_started",
            "port": int(os.environ.get("PORT", "3001")),
        },
    )
    yield
    if _source:
        _source.stop()


app = FastAPI(title="AquaSense", lifespan=lifespan)
templates = Jinja2Templates(directory=str(ROOT / "templates"))
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "topics": list(TOPICS.values()),
        "lastReading": pubsub.get_last(TOPICS["SENSOR_DATA"]),
        "status": pubsub.get_last(TOPICS["SENSOR_STATUS"]),
    }


@app.get("/api/latest")
async def latest() -> dict[str, Any]:
    return {
        "data": pubsub.get_last(TOPICS["SENSOR_DATA"]),
        "status": pubsub.get_last(TOPICS["SENSOR_STATUS"]),
    }


@app.websocket("/ws")
async def websocket_hub(websocket: WebSocket) -> None:
    await websocket.accept()
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    unsubscribers: list[Any] = []

    def make_handler(topic: str):
        def handler(payload: Any) -> None:
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "message", "topic": topic, "payload": payload},
            )

        return handler

    async def send_json(obj: dict[str, Any]) -> None:
        await websocket.send_json(obj)

    await send_json(
        {
            "type": "welcome",
            "topics": list(TOPICS.values()),
            "message": "Water Sensors WebSocket hub ready. Subscribe to topics.",
        }
    )

    for topic in (
        TOPICS["SENSOR_DATA"],
        TOPICS["SENSOR_STATUS"],
        TOPICS["SYSTEM"],
    ):
        unsubscribers.append(pubsub.subscribe(topic, make_handler(topic)))

    await send_json(
        {
            "type": "subscribed",
            "topics": [
                TOPICS["SENSOR_DATA"],
                TOPICS["SENSOR_STATUS"],
                TOPICS["SYSTEM"],
            ],
        }
    )

    async def reader() -> None:
        while True:
            raw = await websocket.receive_json()
            action = raw.get("action")
            if action == "ping":
                await send_json({"type": "pong", "timestamp": _now()})
            elif action == "subscribe" and isinstance(raw.get("topics"), list):
                for topic in raw["topics"]:
                    unsubscribers.append(pubsub.subscribe(topic, make_handler(topic)))
                await send_json({"type": "subscribed", "topics": raw["topics"]})
            elif action == "unsubscribe" and isinstance(raw.get("topics"), list):
                await send_json({"type": "unsubscribed", "topics": raw["topics"]})
            else:
                await send_json({"type": "error", "message": "Unknown action"})

    async def writer() -> None:
        while True:
            msg = await queue.get()
            await send_json(msg)

    try:
        await asyncio.gather(reader(), writer())
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        pass
    finally:
        for unsub in unsubscribers:
            unsub()


def main() -> None:
    parser = argparse.ArgumentParser(description="AquaSense water monitoring server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "3001")))
    args = parser.parse_args()

    import uvicorn

    print(f"[server] http://localhost:{args.port}")
    print(f"[server] websocket ws://localhost:{args.port}/ws")
    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
