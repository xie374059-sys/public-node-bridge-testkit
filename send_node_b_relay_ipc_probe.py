#!/usr/bin/env python3
"""Send one safe Node-B relay-to-Codex IPC probe and wait for relay result."""

from __future__ import annotations

import argparse
import json
import os
import time
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


DEFAULT_MARKER = "NODEB-RELAY-IPC-001"
DEFAULT_EXPECTED = "STATUS=NODEB_RELAY_IPC_OK; MARKER=NODEB_RELAY_IPC_001; NEXT=RELAY_IPC_REPEAT"
EXPECTED_EXECUTION = "node_b_relay_to_codex_ipc_start_turn"


def cannot_claim() -> list[str]:
    return [
        "formal_ack",
        "external_send",
        "file_execution",
        "persistent_service",
        "long_running_autonomy",
        "production_ready_connection",
        "frontstage_auto_injection",
        "input_box_automation",
    ]


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
            return json.loads(exc.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "error": str(exc)}


def result_passed(result: dict[str, Any], expected: str) -> bool:
    return (
        result.get("status") == "ok"
        and result.get("agent_message") == expected
        and result.get("task_sent_to_codex") is True
        and result.get("codex_exact_reply_observed") is True
        and result.get("completion_observed") is True
        and result.get("execution") == EXPECTED_EXECUTION
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Send one safe Node-B relay-to-Codex IPC probe.")
    parser.add_argument("--relay-url", required=True)
    parser.add_argument("--token", default=os.environ.get("NODE_BRIDGE_TOKEN", ""))
    parser.add_argument("--node-id", default="node-b")
    parser.add_argument("--marker", default=DEFAULT_MARKER)
    parser.add_argument("--expected", default=DEFAULT_EXPECTED)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--interval", type=float, default=2.0)
    args = parser.parse_args()

    relay = args.relay_url.rstrip("/")
    created = http_json(
        "POST",
        f"{relay}/tasks",
        {
            "target_node": args.node_id,
            "task_type": "reply_exactly",
            "payload": {
                "marker": args.marker,
                "text": args.expected,
            },
        },
        token=args.token,
    )
    if not created.get("ok"):
        print(json.dumps({"ok": False, "stage": "create_task", "response": created}, ensure_ascii=False, indent=2))
        return 1

    task_id = str(created["task"]["task_id"])
    deadline = time.monotonic() + args.timeout
    latest: dict[str, Any] = {}
    while time.monotonic() < deadline:
        latest = http_json("GET", f"{relay}/tasks/{task_id}", token=args.token)
        task = latest.get("task") if isinstance(latest.get("task"), dict) else {}
        result = task.get("result") if isinstance(task.get("result"), dict) else {}
        if task.get("status") == "completed":
            ok = result_passed(result, args.expected)
            print(json.dumps({
                "ok": ok,
                "relay": relay,
                "node_id": args.node_id,
                "task_id": task_id,
                "status": task.get("status"),
                "marker": result.get("marker"),
                "agent_message": result.get("agent_message"),
                "task_sent_to_codex": result.get("task_sent_to_codex"),
                "codex_exact_reply_observed": result.get("codex_exact_reply_observed"),
                "completion_observed": result.get("completion_observed"),
                "execution": result.get("execution"),
                "probe_claim": result.get("probe_claim"),
                "claim": "node_b_relay_ipc_probe_passed" if ok else "node_b_relay_ipc_probe_result_mismatch",
                "cannot_claim": cannot_claim(),
            }, ensure_ascii=False, indent=2))
            return 0 if ok else 1
        time.sleep(args.interval)

    print(json.dumps({
        "ok": False,
        "relay": relay,
        "node_id": args.node_id,
        "task_id": task_id,
        "status": "timeout",
        "latest": latest,
        "claim": "node_b_relay_ipc_probe_timeout",
        "cannot_claim": cannot_claim(),
    }, ensure_ascii=False, indent=2))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
