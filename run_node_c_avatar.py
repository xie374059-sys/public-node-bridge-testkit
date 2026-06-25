#!/usr/bin/env python3
"""Run the local-only Node-C avatar health and light-task check."""

from __future__ import annotations

import argparse
import json
import socket
import threading
import time
from typing import Any
from urllib.request import Request, urlopen

from node_bridge_testkit.avatar_runtime import DEFAULT_INSTALL_DIR, health_packet, load_avatar, update_state
from node_bridge_testkit.node_adapter import run_once
from node_bridge_testkit.relay import make_server


CHECKS = [
    (
        "NODEC-AVATAR-HEALTH",
        "STATUS=NODEC_AVATAR_HEALTH_OK; MARKER=NODEC_AVATAR_HEALTH; NEXT=READY_FOR_LIGHT_TASK",
    ),
    (
        "NODEC-AVATAR-LIGHT",
        "STATUS=NODEC_AVATAR_TASK_OK; MARKER=NODEC_AVATAR_LIGHT; NEXT=READY_FOR_FILE_PREFLIGHT",
    ),
]


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


def create_reply_task(relay_url: str, node_id: str, marker: str, expected: str) -> str:
    created = http_json(
        "POST",
        f"{relay_url}/tasks",
        {
            "target_node": node_id,
            "task_type": "reply_exactly",
            "payload": {
                "marker": marker,
                "text": expected,
            },
        },
    )
    return str(created["task"]["task_id"])


def assert_result(relay_url: str, task_id: str, expected: str) -> dict[str, Any]:
    task = http_json("GET", f"{relay_url}/tasks/{task_id}")["task"]
    result = task.get("result") or {}
    if task.get("status") != "completed":
        raise AssertionError(f"{task_id} not completed: {task.get('status')}")
    if result.get("agent_message") != expected:
        raise AssertionError(f"{task_id} expected {expected!r}, got {result.get('agent_message')!r}")
    return task


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local-only Node-C avatar.")
    parser.add_argument("--install-dir", default=DEFAULT_INSTALL_DIR)
    args = parser.parse_args()

    root, config, state = load_avatar(args.install_dir)
    node_id = str(config["node_id"])
    health = health_packet(config)

    port = free_port()
    server = make_server("127.0.0.1", port, quiet=True)
    relay_url = f"http://127.0.0.1:{port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)

    completed: list[dict[str, str]] = []
    try:
        if not http_json("GET", f"{relay_url}/health").get("ok"):
            raise AssertionError("relay health failed")

        for marker, expected in CHECKS:
            task_id = create_reply_task(relay_url, node_id, marker, expected)
            handled = run_once(relay_url, node_id)
            if not handled.get("handled"):
                raise AssertionError(f"node adapter did not handle {task_id}")
            task = assert_result(relay_url, task_id, expected)
            completed.append({
                "marker": marker,
                "task_id": task_id,
                "agent_message": task["result"]["agent_message"],
                "execution": task["result"]["execution"],
            })

        claim = "node_c_avatar_installer_local_run_passed"
        updated_state = update_state(root, state, claim)
        print(json.dumps({
            "ok": True,
            "node_id": node_id,
            "install_dir": str(root),
            "health": health,
            "completed": completed,
            "state": {
                "last_heartbeat_at": updated_state["last_heartbeat_at"],
                "last_run_claim": updated_state["last_run_claim"],
            },
            "claim": claim,
            "cannot_claim": [
                "real_codex_ipc",
                "external_node_connected",
                "formal_ack",
                "external_send",
                "file_execution",
                "persistent_service",
                "long_running_autonomy",
            ],
        }, ensure_ascii=False, indent=2))
        return 0
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
