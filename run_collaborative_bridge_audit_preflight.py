#!/usr/bin/env python3
"""Run a local collaborative bridge audit preflight.

This verifies that the collaborative bridge writes append-only audit events for
task creation, approval, execution state changes, result review, and completion.
"""

from __future__ import annotations

import json
import socket
import tempfile
import threading
import time
from pathlib import Path
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
                "prompt": "Inspect the failing test summary and propose a minimal fix.",
                "capabilities": [
                    "send_prompt_to_codex",
                    "read_task_result",
                    "return_artifact_summary",
                ],
            },
        },
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        audit_path = Path(temp_dir) / "collaborative_audit.jsonl"
        port = free_port()
        server = make_server("127.0.0.1", port, quiet=True, audit_path=audit_path)
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

            for status in ("sent_to_codex", "running", "result_pending_review"):
                updated = http_json(
                    "POST",
                    f"{relay_url}/tasks/{task_id}/state",
                    {"node_id": NODE_ID, "status": status},
                )
                if updated["task"]["status"] != status:
                    raise AssertionError(f"state update failed: {status}: {updated}")

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
            if completed["task"]["status"] != "completed":
                raise AssertionError(f"completion failed: {completed}")

            if not audit_path.exists():
                raise AssertionError(f"missing audit log: {audit_path}")

            lines = [line for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            if len(lines) < 3:
                raise AssertionError(f"expected audit events, got {len(lines)} lines")

            events = [json.loads(line) for line in lines]
            event_types = [event.get("event_type") for event in events]
            required = {
                "task_created",
                "task_approved",
                "task_sent_to_codex",
                "task_running",
                "task_result_pending_review",
                "task_completed",
            }
            if not required.issubset(set(event_types)):
                raise AssertionError(f"missing audit events: {event_types}")
            completion_events = [event for event in events if event.get("event_type") == "task_completed"]
            if any("agent_message" in event.get("details", {}) for event in completion_events):
                raise AssertionError("audit log must not store full agent_message")

            print(json.dumps({
                "ok": True,
                "relay": relay_url,
                "audit_path": str(audit_path),
                "event_types": event_types,
                "claim": "collaborative_bridge_audit_passed",
                "cannot_claim": [
                    "real_codex_ipc",
                    "hidden_background_control",
                    "shell_execution",
                    "arbitrary_file_read",
                    "external_send",
                ],
            }, ensure_ascii=False, indent=2))
            return 0
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
