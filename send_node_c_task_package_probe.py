#!/usr/bin/env python3
"""Send one safe allowlisted task-package probe to Node-C and wait for result."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import time
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


DEFAULT_MARKER = "NODEC-PACKAGE-001"
DEFAULT_FILENAME = "nodec_task_package_001.json"
DEFAULT_PACKAGE = {
    "schema": "yuanjie_task_package_v0.1",
    "marker": DEFAULT_MARKER,
    "action": "count_lines",
    "input_text": "alpha\nbeta\ngamma\n",
    "expected_line_count": 3,
    "boundary": {
        "shell_execution": False,
        "file_execution": False,
        "external_send": False,
    },
}


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Send one safe Node-C task-package probe.")
    parser.add_argument("--relay-url", required=True)
    parser.add_argument("--token", default=os.environ.get("NODE_BRIDGE_TOKEN", ""))
    parser.add_argument("--node-id", default="node-c")
    parser.add_argument("--marker", default=DEFAULT_MARKER)
    parser.add_argument("--filename", default=DEFAULT_FILENAME)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--interval", type=float, default=2.0)
    args = parser.parse_args()

    relay = args.relay_url.rstrip("/")
    package = dict(DEFAULT_PACKAGE)
    package["marker"] = args.marker
    package_bytes = json.dumps(package, ensure_ascii=False, indent=2).encode("utf-8")
    expected_sha256 = hashlib.sha256(package_bytes).hexdigest()
    created = http_json(
        "POST",
        f"{relay}/tasks",
        {
            "target_node": args.node_id,
            "task_type": "task_package",
            "payload": {
                "marker": args.marker,
                "filename": args.filename,
                "content_b64": base64.b64encode(package_bytes).decode("ascii"),
                "sha256": expected_sha256,
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
        task = latest.get("task") or {}
        result = task.get("result") or {}
        if task.get("status") == "completed":
            ok = (
                result.get("status") == "ok"
                and result.get("marker") == args.marker
                and result.get("filename") == args.filename
                and result.get("sha256") == expected_sha256
                and result.get("execution") == "local_adapter_task_package_execute_allowlist"
                and result.get("action") == "count_lines"
                and result.get("line_count") == 3
            )
            print(json.dumps({
                "ok": ok,
                "relay": relay,
                "node_id": args.node_id,
                "task_id": task_id,
                "status": task.get("status"),
                "marker": result.get("marker"),
                "filename": result.get("filename"),
                "bytes": result.get("bytes"),
                "sha256": result.get("sha256"),
                "saved_to": result.get("saved_to"),
                "action": result.get("action"),
                "line_count": result.get("line_count"),
                "claim": "node_c_task_package_preflight_passed" if ok else "node_c_task_package_result_mismatch",
                "cannot_claim": [
                    "real_codex_ipc",
                    "formal_ack",
                    "external_send",
                    "arbitrary_file_execution",
                    "persistent_service",
                    "long_running_autonomy",
                ],
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
        "claim": "node_c_task_package_preflight_timeout",
        "cannot_claim": [
            "real_codex_ipc",
            "formal_ack",
            "external_send",
            "arbitrary_file_execution",
        ],
    }, ensure_ascii=False, indent=2))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
