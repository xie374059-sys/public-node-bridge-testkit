#!/usr/bin/env python3
"""Run an optional Codex IPC collaborative bridge end-to-end preflight."""

from __future__ import annotations

import argparse
import base64
import json
import socket
import threading
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from node_bridge_testkit.relay import make_server
from run_collaborative_bridge_codex_ipc_backend import main as run_backend_main


NODE_ID = "node-c"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def http_json(method: str, url: str, body: dict[str, Any] | None = None, token: str = "") -> dict[str, Any]:
    data = None
    headers = {"accept": "application/json"}
    if token:
        headers["X-Node-Bridge-Token"] = token
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["content-type"] = "application/json"
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except Exception:
            payload = {"ok": False, "error": str(exc)}
        payload["http_status"] = exc.code
        return payload


def create_task(relay_url: str) -> dict[str, Any]:
    return http_json(
        "POST",
        f"{relay_url}/tasks",
        {
            "target_node": NODE_ID,
            "task_type": "collaborative_bridge",
            "payload": {
                "requester": "yuanjie-controller",
                "target_project": "D:\\test001\\public-node-bridge-testkit",
                "prompt": "Reply exactly: NODEC_COLLAB_IPC_OK_001",
                "capabilities": ["send_prompt_to_codex", "read_task_result"],
            },
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the optional Codex IPC collaborative preflight.")
    parser.add_argument("--session-binding", default=".node_c_avatar/session_binding.json")
    parser.add_argument("--marker", default="NODEC_COLLAB_IPC_OK_001")
    parser.add_argument("--observe-timeout", type=float, default=120.0)
    args = parser.parse_args()

    if not Path(args.session_binding).expanduser().exists():
        print(json.dumps({
            "ok": False,
            "error": "missing_session_binding",
            "claim": "collaborative_bridge_codex_ipc_preflight_missing_binding",
            "cannot_claim": [],
        }, ensure_ascii=False, indent=2))
        return 1

    port = free_port()
    server = make_server("127.0.0.1", port, quiet=True)
    relay_url = f"http://127.0.0.1:{port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)

    try:
        created = create_task(relay_url)
        if not created.get("ok"):
            raise AssertionError(f"task creation failed: {created}")
        task_id = created["task"]["task_id"]
        approved = http_json(
            "POST",
            f"{relay_url}/tasks/{task_id}/approval",
            {"node_id": NODE_ID, "decision": "approve"},
        )
        if approved["task"]["status"] != "approved":
            raise AssertionError(f"approval failed: {approved}")

        backend_argv = [
            "run_collaborative_bridge_codex_ipc_backend.py",
            "--relay-url",
            relay_url,
            "--task-id",
            task_id,
            "--session-binding",
            args.session_binding,
            "--marker",
            args.marker,
            "--observe-timeout",
            str(args.observe_timeout),
        ]
        import sys
        old_argv = sys.argv
        try:
            sys.argv = backend_argv
            backend_exit = run_backend_main()
        finally:
            sys.argv = old_argv

        final_task = http_json("GET", f"{relay_url}/tasks/{task_id}")
        task = final_task.get("task") if isinstance(final_task.get("task"), dict) else {}
        if backend_exit != 0 or task.get("status") != "completed":
            print(json.dumps({
                "ok": False,
                "relay": relay_url,
                "task_id": task_id,
                "backend_exit": backend_exit,
                "task_status": task.get("status"),
                "claim": "collaborative_bridge_codex_ipc_preflight_incomplete",
                "cannot_claim": [
                    "thread_follower_start_turn_usable",
                    "task_sent_to_codex_completed",
                    "codex_reply_read",
                    "remote_desktop_control",
                    "hidden_background_control",
                    "production_ready_collaboration",
                ],
            }, ensure_ascii=False, indent=2))
            return 1
        result = task.get("result") if isinstance(task.get("result"), dict) else {}
        if result.get("agent_message") != args.marker:
            raise AssertionError(f"unexpected result: {result}")

        print(json.dumps({
            "ok": True,
            "relay": relay_url,
            "task_id": task_id,
            "session_binding": args.session_binding,
            "marker": args.marker,
            "claim": "collaborative_bridge_codex_ipc_preflight_passed",
            "cannot_claim": [
                "remote_desktop_control",
                "hidden_background_control",
                "production_ready_collaboration",
            ],
        }, ensure_ascii=False, indent=2))
        return 0
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
