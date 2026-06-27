#!/usr/bin/env python3
"""Run a local collaborative bridge state-transition preflight."""

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


def create_task(relay_url: str) -> dict[str, Any]:
    return http_json(
        "POST",
        f"{relay_url}/tasks",
        {
            "target_node": NODE_ID,
            "task_type": "collaborative_bridge",
            "payload": {
                "requester": "yuanjie-controller",
                "target_project": "D:\\work\\repo-b",
                "prompt": "Reply exactly: NODEC_COLLAB_IPC_OK_001",
                "capabilities": ["send_prompt_to_codex", "read_task_result"],
            },
        },
    )


def transition(relay_url: str, task_id: str, status: str) -> dict[str, Any]:
    return http_json(
        "POST",
        f"{relay_url}/tasks/{task_id}/state",
        {"node_id": NODE_ID, "status": status},
    )


def main() -> int:
    port = free_port()
    server = make_server("127.0.0.1", port, quiet=True)
    relay_url = f"http://127.0.0.1:{port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)

    try:
        created = create_task(relay_url)
        task_id = created["task"]["task_id"]
        denied = transition(relay_url, task_id, "sent_to_codex")
        if denied.get("ok") is not False or denied.get("http_status") != 400:
            raise AssertionError(f"unapproved task state transition was not rejected: {denied}")

        approved = http_json(
            "POST",
            f"{relay_url}/tasks/{task_id}/approval",
            {"node_id": NODE_ID, "decision": "approve"},
        )
        if approved["task"]["status"] != "approved":
            raise AssertionError(f"approval failed: {approved}")

        seen: list[str] = []
        for status in ("sent_to_codex", "running", "result_pending_review"):
            updated = transition(relay_url, task_id, status)
            if updated["task"]["status"] != status:
                raise AssertionError(f"expected {status}, got {updated}")
            seen.append(status)

        completed = http_json(
            "POST",
            f"{relay_url}/tasks/{task_id}/result",
            {
                "node_id": NODE_ID,
                "result": {
                    "status": "ok",
                    "agent_message": "NODEC_COLLAB_IPC_OK_001",
                    "execution": "codex_ipc_start_turn",
                },
            },
        )
        if completed["task"]["status"] != "completed":
            raise AssertionError(f"completion failed: {completed}")

        print(json.dumps({
            "ok": True,
            "relay": relay_url,
            "task_id": task_id,
            "states": seen,
            "claim": "collaborative_bridge_state_transitions_passed",
            "cannot_claim": [
                "real_codex_ipc",
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
