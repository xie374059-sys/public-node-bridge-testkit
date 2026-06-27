#!/usr/bin/env python3
"""Run collaborative bridge allowlisted-command execution preflight."""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from node_bridge_testkit.relay import make_server
from run_collaborative_bridge_command_worker import main as run_worker_main


NODE_ID = "node-c"


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


def main() -> int:
    port = free_port()
    server = make_server("127.0.0.1", port, quiet=True)
    relay_url = f"http://127.0.0.1:{port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)

    try:
        forbidden = http_json(
            "POST",
            f"{relay_url}/tasks",
            {
                "target_node": NODE_ID,
                "task_type": "collaborative_bridge",
                "payload": {
                    "requester": "yuanjie-controller",
                    "target_project": "D:\\test001\\public-node-bridge-testkit",
                    "prompt": "Run local demo without capability.",
                    "capabilities": ["read_task_result"],
                    "execution_request": {
                        "kind": "allowlisted_command",
                        "command_id": "local_demo",
                    },
                },
            },
        )
        if forbidden.get("ok") is not False or forbidden.get("http_status") != 400:
            raise AssertionError(f"execution request without capability was not rejected: {forbidden}")

        created = http_json(
            "POST",
            f"{relay_url}/tasks",
            {
                "target_node": NODE_ID,
                "task_type": "collaborative_bridge",
                "payload": {
                    "requester": "yuanjie-controller",
                    "target_project": "D:\\test001\\public-node-bridge-testkit",
                    "prompt": "Run local demo through Host allowlisted command worker.",
                    "capabilities": ["run_project_command", "read_task_result"],
                    "execution_request": {
                        "kind": "allowlisted_command",
                        "command_id": "local_demo",
                    },
                },
            },
        )
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

        old_argv = sys.argv
        try:
            sys.argv = [
                "run_collaborative_bridge_command_worker.py",
                "--relay-url",
                relay_url,
                "--project-root",
                ".",
                "--timeout",
                "30",
            ]
            worker_exit = run_worker_main()
        finally:
            sys.argv = old_argv
        if worker_exit != 0:
            raise AssertionError(f"worker failed: {worker_exit}")

        final_task = http_json("GET", f"{relay_url}/tasks/{task_id}")
        task = final_task.get("task") if isinstance(final_task.get("task"), dict) else {}
        result = task.get("result") if isinstance(task.get("result"), dict) else {}
        if task.get("status") != "completed":
            raise AssertionError(f"task was not completed: {final_task}")
        if result.get("execution") != "host_allowlisted_command":
            raise AssertionError(f"unexpected execution: {result}")
        if result.get("command_id") != "local_demo" or result.get("exit_code") != 0:
            raise AssertionError(f"unexpected command result: {result}")
        if "local_public_testkit_l0_l1_passed" not in str(result.get("stdout", "")):
            raise AssertionError("worker stdout does not include local demo success claim")

        print(json.dumps({
            "ok": True,
            "relay": relay_url,
            "task_id": task_id,
            "command_id": result.get("command_id"),
            "exit_code": result.get("exit_code"),
            "claim": "collaborative_bridge_allowlisted_command_preflight_passed",
            "cannot_claim": [
                "arbitrary_shell_execution",
                "hidden_background_control",
                "unapproved_execution",
                "production_ready_remote_control",
            ],
        }, ensure_ascii=False, indent=2))
        return 0
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
