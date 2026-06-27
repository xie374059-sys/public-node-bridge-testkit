#!/usr/bin/env python3
"""Run a local collaborative bridge lifecycle preflight.

This proves only the relay-side approval lifecycle for a collaborative task.
It does not use Codex IPC, automate a desktop session, read project files, or
execute shell commands.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from node_bridge_testkit.relay import make_server


NODE_ID = "node-c"
REQUESTER = "yuanjie-controller"
PROJECT = "D:\\work\\repo-b"
PROMPT = "Inspect the failing test summary and propose a minimal fix."


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


def create_collaborative_task(relay_url: str, capabilities: list[str] | None = None) -> dict[str, Any]:
    return http_json(
        "POST",
        f"{relay_url}/tasks",
        {
            "target_node": NODE_ID,
            "task_type": "collaborative_bridge",
            "payload": {
                "requester": REQUESTER,
                "target_project": PROJECT,
                "prompt": PROMPT,
                "capabilities": capabilities or [
                    "send_prompt_to_codex",
                    "read_task_result",
                    "return_artifact_summary",
                ],
            },
        },
    )


def main() -> int:
    port = free_port()
    server = make_server("127.0.0.1", port, quiet=True)
    relay_url = f"http://127.0.0.1:{port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)

    try:
        denied = create_collaborative_task(relay_url, ["shell_execution"])
        if denied.get("ok") is not False or denied.get("http_status") != 400:
            raise AssertionError(f"forbidden capability was not rejected: {denied}")

        created = create_collaborative_task(relay_url)
        if not created.get("ok"):
            raise AssertionError(f"collaborative task creation failed: {created}")
        task = created["task"]
        task_id = task["task_id"]
        if task["status"] != "pending_approval":
            raise AssertionError(f"{task_id} expected pending_approval, got {task['status']}")
        if not task.get("audit_id"):
            raise AssertionError(f"{task_id} missing audit_id")

        polled = http_json("GET", f"{relay_url}/poll?node_id={NODE_ID}")
        if polled.get("task") is not None:
            raise AssertionError(f"pending approval task was returned by poll: {polled}")

        rejected = create_collaborative_task(relay_url)
        rejected_id = rejected["task"]["task_id"]
        reject_response = http_json(
            "POST",
            f"{relay_url}/tasks/{rejected_id}/approval",
            {"node_id": NODE_ID, "decision": "reject", "reason": "Need clearer scope."},
        )
        if reject_response["task"]["status"] != "rejected":
            raise AssertionError(f"{rejected_id} was not rejected: {reject_response}")

        approved = http_json(
            "POST",
            f"{relay_url}/tasks/{task_id}/approval",
            {"node_id": NODE_ID, "decision": "approve"},
        )
        if approved["task"]["status"] != "approved":
            raise AssertionError(f"{task_id} was not approved: {approved}")
        if not approved["task"].get("approved_at"):
            raise AssertionError(f"{task_id} missing approved_at")

        completed = http_json(
            "POST",
            f"{relay_url}/tasks/{task_id}/result",
            {
                "node_id": NODE_ID,
                "result": {
                    "status": "ok",
                    "agent_message": "Host-approved manual bridge result.",
                    "execution": "manual_codex_bridge",
                },
            },
        )
        final_task = completed["task"]
        if final_task["status"] != "completed":
            raise AssertionError(f"{task_id} was not completed: {completed}")

        print(json.dumps({
            "ok": True,
            "relay": relay_url,
            "task_id": task_id,
            "rejected_task_id": rejected_id,
            "claim": "collaborative_bridge_relay_lifecycle_passed",
            "cannot_claim": [
                "real_codex_ipc",
                "remote_desktop_control",
                "hidden_background_control",
                "shell_execution",
                "arbitrary_file_read",
                "external_send",
                "production_ready_collaboration",
            ],
        }, ensure_ascii=False, indent=2))
        return 0
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
