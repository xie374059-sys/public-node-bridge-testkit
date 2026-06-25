#!/usr/bin/env python3
"""Run an end-to-end local demo.

This starts a local relay in-process, posts L0/L1 light tasks, lets a mock node
complete them, and verifies the returned messages. No network service outside
localhost is used.
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
from typing import Any
from urllib.request import Request, urlopen

from node_bridge_testkit.mock_node import run_once
from node_bridge_testkit.relay import make_server


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def http_json(method: str, url: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None
    headers = {"accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["content-type"] = "application/json"
    req = Request(url, data=data, headers=headers, method=method)
    with urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def create_reply_task(relay_url: str, marker: str, expected: str) -> str:
    created = http_json(
        "POST",
        f"{relay_url}/tasks",
        {
            "target_node": "node-b",
            "task_type": "reply_exactly",
            "payload": {
                "marker": marker,
                "text": expected,
            },
        },
    )
    return str(created["task"]["task_id"])


def assert_result(relay_url: str, task_id: str, expected: str) -> None:
    task = http_json("GET", f"{relay_url}/tasks/{task_id}")["task"]
    result = task.get("result") or {}
    agent_message = result.get("agent_message")
    if task.get("status") != "completed":
        raise AssertionError(f"{task_id} not completed: {task.get('status')}")
    if agent_message != expected:
        raise AssertionError(f"{task_id} expected {expected!r}, got {agent_message!r}")


def main() -> int:
    port = free_port()
    server = make_server("127.0.0.1", port, quiet=True)
    relay_url = f"http://127.0.0.1:{port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)

    try:
        health = http_json("GET", f"{relay_url}/health")
        if not health.get("ok"):
            raise AssertionError("relay health failed")

        tests = [
            ("L0-OK", "OK"),
            ("L1-STRUCT", "STATUS=READ_OK; MARKER=PUBLIC_L1; NEXT=SMALL_TASK"),
        ]
        completed: list[dict[str, str]] = []
        for marker, expected in tests:
            task_id = create_reply_task(relay_url, marker, expected)
            handled = run_once(relay_url, "node-b")
            if not handled.get("handled"):
                raise AssertionError(f"mock node did not handle {task_id}")
            assert_result(relay_url, task_id, expected)
            completed.append({"marker": marker, "task_id": task_id, "agent_message": expected})

        print(json.dumps({
            "ok": True,
            "relay": relay_url,
            "completed": completed,
            "claim": "local_public_testkit_l0_l1_passed",
            "cannot_claim": [
                "real_codex_ipc",
                "external_node_connected",
                "formal_ack",
                "external_send",
            ],
        }, ensure_ascii=False, indent=2))
        return 0
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
