#!/usr/bin/env python3
"""Poll a remote relay as Node-C and complete safe light tasks."""

from __future__ import annotations

import argparse
import json
import os
import time

from node_bridge_testkit.avatar_runtime import DEFAULT_INSTALL_DIR, load_avatar, update_state
from node_bridge_testkit.node_adapter import run_once


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Node-C against a remote relay.")
    parser.add_argument("--relay-url", required=True)
    parser.add_argument("--token", default=os.environ.get("NODE_BRIDGE_TOKEN", ""))
    parser.add_argument("--install-dir", default=DEFAULT_INSTALL_DIR)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--max-tasks", type=int, default=1)
    args = parser.parse_args()

    root, config, state = load_avatar(args.install_dir)
    node_id = str(config["node_id"])
    relay = args.relay_url.rstrip("/")
    deadline = time.monotonic() + args.timeout
    completed: list[dict[str, object]] = []

    while time.monotonic() < deadline and len(completed) < args.max_tasks:
        result = run_once(relay, node_id, token=args.token)
        if not result.get("ok"):
            print(json.dumps({"ok": False, "stage": "poll_or_submit", "result": result}, ensure_ascii=False, indent=2))
            return 1
        if result.get("handled"):
            posted = result.get("posted") if isinstance(result.get("posted"), dict) else {}
            task = posted.get("task") if isinstance(posted.get("task"), dict) else {}
            task_result = task.get("result") if isinstance(task.get("result"), dict) else {}
            completed.append({
                "task_id": result.get("task_id"),
                "marker": task_result.get("marker"),
                "agent_message": task_result.get("agent_message"),
                "execution": task_result.get("execution"),
            })
        else:
            time.sleep(args.interval)

    ok = bool(completed)
    claim = "node_c_remote_client_completed_task" if ok else "node_c_remote_client_timeout_no_task"
    updated_state = update_state(root, state, claim)
    print(json.dumps({
        "ok": ok,
        "relay": relay,
        "node_id": node_id,
        "completed": completed,
        "state": {
            "last_heartbeat_at": updated_state["last_heartbeat_at"],
            "last_run_claim": updated_state["last_run_claim"],
        },
        "claim": claim,
        "cannot_claim": [
            "real_codex_ipc",
            "formal_ack",
            "external_send",
            "file_execution",
            "persistent_service",
            "long_running_autonomy",
        ],
    }, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
