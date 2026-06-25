#!/usr/bin/env python3
"""Safe local node adapter for the public node bridge testkit.

This adapter is intentionally narrow. It handles only allowlisted light tasks
and never executes shell commands, opens local files, sends messages, or touches
private data.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DENIED_CAPABILITIES = [
    "shell_execution",
    "file_read",
    "arbitrary_file_write",
    "file_execution",
    "external_send",
    "private_endpoint_routing",
]

MAX_FILE_BYTES = 64 * 1024


def safe_filename(name: str) -> str:
    cleaned = name.strip().replace("\\", "/").split("/")[-1]
    if not cleaned or cleaned in {".", ".."}:
        raise ValueError("invalid filename")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
    safe = "".join(char for char in cleaned if char in allowed)
    if not safe:
        raise ValueError("filename has no safe characters")
    return safe[:120]


def http_json(method: str, url: str, body: dict[str, Any] | None = None, token: str = "") -> dict[str, Any]:
    data = None
    headers = {"accept": "application/json"}
    if token:
        headers["X-Node-Bridge-Token"] = token
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["content-type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except Exception:
            payload = {"ok": False, "error": str(exc)}
        return payload


def execute_task(task: dict[str, Any], node_id: str, sandbox_dir: str | Path = "") -> dict[str, Any]:
    task_type = task.get("task_type")
    payload = task.get("payload") or {}
    if task_type == "reply_exactly":
        text = payload.get("text")
        if not isinstance(text, str):
            return {"status": "error", "error": "missing payload.text"}
        return {
            "status": "ok",
            "node_id": node_id,
            "marker": str(payload.get("marker", "")),
            "agent_message": text,
            "execution": "local_adapter_reply_exactly",
            "safe_mode": True,
            "denied_capabilities": DENIED_CAPABILITIES,
        }
    if task_type == "file_deliver":
        try:
            filename = safe_filename(str(payload.get("filename", "payload.txt")))
            content_b64 = payload.get("content_b64")
            expected_sha256 = str(payload.get("sha256", ""))
            if not isinstance(content_b64, str):
                return {"status": "error", "error": "missing payload.content_b64"}
            raw = base64.b64decode(content_b64.encode("ascii"), validate=True)
            if len(raw) > MAX_FILE_BYTES:
                return {"status": "error", "error": "file_too_large"}
            actual_sha256 = hashlib.sha256(raw).hexdigest()
            if expected_sha256 and actual_sha256 != expected_sha256:
                return {"status": "error", "error": "sha256_mismatch", "sha256": actual_sha256}
            root = Path(sandbox_dir or ".node_c_avatar").expanduser().resolve()
            inbox = root / "inbox" / str(task.get("task_id", "task_unknown"))
            inbox.mkdir(parents=True, exist_ok=True)
            path = inbox / filename
            path.write_bytes(raw)
            return {
                "status": "ok",
                "node_id": node_id,
                "marker": str(payload.get("marker", "")),
                "filename": filename,
                "bytes": len(raw),
                "sha256": actual_sha256,
                "saved_to": str(path),
                "execution": "local_adapter_file_deliver_sandbox_write",
                "safe_mode": True,
                "allowed_capability": "sandbox_file_write",
                "denied_capabilities": DENIED_CAPABILITIES,
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)}
    return {"status": "error", "error": f"unsupported task_type: {task_type}"}


def run_once(relay_url: str, node_id: str, token: str = "", sandbox_dir: str | Path = "") -> dict[str, Any]:
    poll_url = f"{relay_url.rstrip('/')}/poll?{urlencode({'node_id': node_id})}"
    polled = http_json("GET", poll_url, token=token)
    task = polled.get("task")
    if not task:
        return {"ok": True, "handled": False, "node_id": node_id}

    result = execute_task(task, node_id, sandbox_dir=sandbox_dir)
    task_id = task["task_id"]
    result_url = f"{relay_url.rstrip('/')}/tasks/{task_id}/result"
    posted = http_json("POST", result_url, {"node_id": node_id, "result": result}, token=token)
    return {"ok": bool(posted.get("ok")), "handled": True, "task_id": task_id, "posted": posted}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a safe local node adapter.")
    parser.add_argument("--relay", default="http://127.0.0.1:8765")
    parser.add_argument("--node-id", default="node-c")
    parser.add_argument("--token", default=os.environ.get("NODE_BRIDGE_TOKEN", ""))
    parser.add_argument("--sandbox-dir", default=".node_c_avatar")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--max-iterations", type=int, default=0)
    args = parser.parse_args()

    iterations = 0
    while True:
        result = run_once(args.relay, args.node_id, token=args.token, sandbox_dir=args.sandbox_dir)
        print(json.dumps(result, ensure_ascii=False))
        iterations += 1
        if args.once:
            return 0 if result.get("ok") else 1
        if args.max_iterations and iterations >= args.max_iterations:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
