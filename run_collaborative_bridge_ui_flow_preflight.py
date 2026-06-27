#!/usr/bin/env python3
"""Run a local collaborative bridge UI form-flow preflight."""

from __future__ import annotations

import json
import socket
import threading
import time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from node_bridge_testkit.relay import make_server


NODE_ID = "node-c"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def read_text(url: str) -> str:
    with urlopen(url, timeout=10) as response:
        return response.read().decode("utf-8")


def post_form(url: str, data: dict[str, str]) -> dict[str, Any]:
    payload = urlencode(data).encode("utf-8")
    req = Request(
        url,
        data=payload,
        headers={"content-type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
        except Exception:
            body = {"ok": False, "error": str(exc)}
        body["http_status"] = exc.code
        return body


def main() -> int:
    port = free_port()
    server = make_server("127.0.0.1", port, quiet=True)
    relay_url = f"http://127.0.0.1:{port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)

    try:
        controller_page = read_text(f"{relay_url}/controller?lang=zh")
        host_page = read_text(f"{relay_url}/host?lang=zh")
        if "name=\"prompt\"" not in controller_page:
            raise AssertionError("controller page missing prompt form field")
        if "待审批任务" not in host_page:
            raise AssertionError("host page missing pending approval area")

        created = post_form(
            f"{relay_url}/ui/controller/tasks",
            {
                "requester": "yuanjie-controller",
                "target_node": NODE_ID,
                "target_project": "D:\\work\\repo-b",
                "prompt": "Inspect the failing test summary and propose a minimal fix.",
                "capabilities": "send_prompt_to_codex,read_task_result,return_artifact_summary",
            },
        )
        if not created.get("ok"):
            raise AssertionError(f"controller task form failed: {created}")
        task_id = created["task"]["task_id"]
        if created["task"]["status"] != "pending_approval":
            raise AssertionError(f"created task is not pending approval: {created}")

        approved = post_form(
            f"{relay_url}/ui/host/approval",
            {"task_id": task_id, "node_id": NODE_ID, "decision": "approve"},
        )
        if approved["task"]["status"] != "approved":
            raise AssertionError(f"host approval form failed: {approved}")

        completed = post_form(
            f"{relay_url}/ui/host/result",
            {
                "task_id": task_id,
                "node_id": NODE_ID,
                "agent_message": "Host-approved manual bridge result.",
            },
        )
        if completed["task"]["status"] != "completed":
            raise AssertionError(f"host result form failed: {completed}")

        controller_after = read_text(f"{relay_url}/controller?lang=en")
        if task_id not in controller_after:
            raise AssertionError("controller page does not show completed task")
        if "Host-approved manual bridge result." not in controller_after:
            raise AssertionError("controller page does not show returned result")

        rejected_created = post_form(
            f"{relay_url}/ui/controller/tasks",
            {
                "requester": "yuanjie-controller",
                "target_node": NODE_ID,
                "target_project": "D:\\work\\repo-b",
                "prompt": "This task should be rejected by the Host.",
                "capabilities": "send_prompt_to_codex,read_task_result",
            },
        )
        rejected_id = rejected_created["task"]["task_id"]
        rejected = post_form(
            f"{relay_url}/ui/host/approval",
            {
                "task_id": rejected_id,
                "node_id": NODE_ID,
                "decision": "reject",
                "reason": "Need clearer scope.",
            },
        )
        if rejected["task"]["status"] != "rejected":
            raise AssertionError(f"host rejection form failed: {rejected}")
        controller_rejected = read_text(f"{relay_url}/controller?lang=zh")
        if rejected_id not in controller_rejected or "rejected" not in controller_rejected:
            raise AssertionError("controller page does not show rejected task")

        command_created = post_form(
            f"{relay_url}/ui/controller/tasks",
            {
                "requester": "yuanjie-controller",
                "target_node": NODE_ID,
                "target_project": "D:\\test001\\public-node-bridge-testkit",
                "prompt": "Run selected Host allowlisted command.",
                "capabilities": "run_project_command,read_task_result,return_artifact_summary",
                "command_id": "local_demo",
            },
        )
        if not command_created.get("ok"):
            raise AssertionError(f"controller command form failed: {command_created}")
        command_payload = command_created["task"].get("payload", {})
        execution_request = command_payload.get("execution_request", {})
        if execution_request.get("command_id") != "local_demo":
            raise AssertionError(f"command form did not create execution_request: {command_created}")
        host_command_page = read_text(f"{relay_url}/host?lang=zh")
        if "allowlisted_command" not in host_command_page or "local_demo" not in host_command_page:
            raise AssertionError("host page does not show allowlisted command request")

        print(json.dumps({
            "ok": True,
            "relay": relay_url,
            "task_id": task_id,
            "rejected_task_id": rejected_id,
            "command_task_id": command_created["task"]["task_id"],
            "claim": "collaborative_bridge_ui_form_flow_passed",
            "cannot_claim": [
                "real_codex_ipc",
                "remote_desktop_control",
                "hidden_background_control",
                "production_ready_ui",
            ],
        }, ensure_ascii=False, indent=2))
        return 0
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
