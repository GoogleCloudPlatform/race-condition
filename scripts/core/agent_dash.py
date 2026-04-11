# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import asyncio
import json
import os
import random
import threading
import time
import uuid
from typing import List, Optional
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from google.cloud import pubsub_v1
from google.cloud.pubsub_v1.subscriber.message import Message

app = FastAPI(root_path="/dash")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ALLOWED_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "agent_dash"}


load_dotenv()
os.environ["PYTHONPATH"] = "."
# Project & Pub/Sub config
PROJECT_ID = os.getenv("PUBSUB_PROJECT_ID", "test-project")
TOPIC_ID = "agent-telemetry"

# Active connections for live feed
connections: List[WebSocket] = []

# Global loop reference for thread-safe WebSocket broadcasting
main_loop: Optional[asyncio.AbstractEventLoop] = None


@app.get("/", response_class=HTMLResponse)
async def get_index():
    global main_loop
    main_loop = asyncio.get_running_loop()
    try:
        with open("web/agent-dash/index.html") as f:
            content = f.read()
            # Replace absolute paths with relative ones for path-based routing
            content = content.replace('src="/', 'src="./')
            content = content.replace('href="/', 'href="./')
            return content
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Index not found</h1>", status_code=404)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    global main_loop
    main_loop = asyncio.get_running_loop()
    await websocket.accept()
    connections.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        connections.remove(websocket)


def pubsub_callback(message: Message) -> None:
    """Callback triggered on new Pub/Sub message."""
    try:
        data = json.loads(message.data.decode("utf-8"))
        # Broadcast to all connected WebSockets
        if main_loop and main_loop.is_running():
            for ws in connections:
                asyncio.run_coroutine_threadsafe(ws.send_json(data), main_loop)
        message.ack()
    except Exception as e:
        print(f"Error processing message: {e}")
        message.nack()


def start_subscriber(stop_event: threading.Event | None = None):
    """Start Pub/Sub subscriber with auto-reconnect on failure.

    Uses exponential backoff (5s-60s) with jitter, modeled on the
    dispatcher.py reconnect pattern.
    """
    if stop_event is None:
        stop_event = threading.Event()

    backoff = 5  # Initial backoff seconds

    while not stop_event.is_set():
        sub_id = f"dash-subscriber-{uuid.uuid4().hex[:8]}"
        subscriber = pubsub_v1.SubscriberClient()
        topic_path = subscriber.topic_path(PROJECT_ID, TOPIC_ID)
        subscription_path = subscriber.subscription_path(PROJECT_ID, sub_id)

        try:
            # 1. Ensure Topic exists
            publisher = pubsub_v1.PublisherClient()
            try:
                publisher.create_topic(name=topic_path)
            except Exception:
                pass

            # 2. Create unique Subscription for this attempt
            try:
                subscriber.create_subscription(name=subscription_path, topic=topic_path)
            except Exception:
                pass

            print(f"Listening for logs on {subscription_path}...")
            streaming_pull_future = subscriber.subscribe(subscription_path, callback=pubsub_callback)

            with subscriber:
                streaming_pull_future.result()

            # Connection was alive before failing -- reset backoff
            backoff = 5

        except KeyboardInterrupt:
            stop_event.set()
        except Exception as e:
            if not stop_event.is_set():
                jitter = random.uniform(0, backoff * 0.25)
                print(f"PubSub subscriber crashed, reconnecting in {backoff + jitter:.1f}s: {e}")
                time.sleep(backoff + jitter)
                backoff = min(backoff * 2, 60)
        finally:
            # Cleanup temporary subscription and close subscriber client
            try:
                subscriber.delete_subscription(request={"subscription": subscription_path})
            except Exception:
                pass
            try:
                subscriber.close()
            except Exception:
                pass


if __name__ == "__main__":
    import uvicorn

    # Run Pub/Sub subscriber in a separate thread
    _stop = threading.Event()
    sub_thread = threading.Thread(target=start_subscriber, args=(_stop,), daemon=True)
    sub_thread.start()

    # Run FastAPI
    port = int(os.getenv("PORT", 8301))
    uvicorn.run(app, host="0.0.0.0", port=port)
