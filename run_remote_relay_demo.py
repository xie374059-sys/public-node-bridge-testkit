#!/usr/bin/env python3
"""Run a token-protected remote-relay simulation on localhost."""

from __future__ import annotations

import json
import socket
import threading
import time
from typing import Any
from urllib.request import Request, urlopen

from node_bridge_testkit.node_adapter import run_once
from node_bridge_testkit.relay import make_server


TOKEN = "local-demo-token"
NODE_ID = "node-c"
MARKER = "NODEC-REMOTE-LOCAL-DEMO"
EXPECTED = "STATUS=NODEC_REMOTE_LOCAL_DEMO_OK; MARKER=NODEC_REMOTE_LOCAL_DEMO; NEXT=REMOTE_REAL_RELAY"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def http_json(method: str, url: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None
    headers = {"accept": "application/json", "X-Node-Bridge-Token": TOKEN}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["content-type"] = "application/json"
    req = Request(url, data=data, headers=headers, method=method)
    with urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    port = free_port()
    server = make_server("127.0.0.1", port, quiet=True, token=TOKEN)
    relay_url = f"http://127.0.0.1:{port}"
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    time.sleep(0.1)

    try:
        health = json.loads(urlopen(f"{relay_url}/health", timeout=10).read().decode("utf-8"))
        if not health.get("auth_required"):
            raise AssertionError("relay auth_required should be true")

        created = http_json(
            "POST",
            f"{relay_url}/tasks",
            {
                "target_node": NODE_ID,
                "task_type": "reply_exactly",
                "payload": {
                    "marker": MARKER,
                    "text": EXPECTED,
                },
            },
        )
        task_id = str(created["task"]["task_id"])
        handled = run_once(relay_url, NODE_ID, token=TOKEN)
        if not handled.get("handled"):
            raise AssertionError(f"remote client did not handle {task_id}")

        task = http_json("GET", f"{relay_url}/tasks/{task_id}")["task"]
        result = task.get("result") or {}
        if result.get("agent_message") != EXPECTED:
            raise AssertionError(f"expected {EXPECTED!r}, got {result.get('agent_message')!r}")

        print(json.dumps({
            "ok": True,
            "relay": relay_url,
            "node_id": NODE_ID,
            "completed": {
                "marker": MARKER,
                "task_id": task_id,
                "agent_message": result["agent_message"],
                "execution": result["execution"],
            },
            "claim": "node_c_remote_relay_local_simulation_passed",
            "cannot_claim": [
                "real_codex_ipc",
                "real_external_node_connected",
                "formal_ack",
                "external_send",
                "file_execution",
            ],
        }, ensure_ascii=False, indent=2))
        return 0
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
