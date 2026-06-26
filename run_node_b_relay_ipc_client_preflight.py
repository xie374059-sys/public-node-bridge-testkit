#!/usr/bin/env python3
"""Local preflight for the Node-B relay-to-Codex IPC client glue.

This uses `--dry-run-ipc`, so it proves only relay polling, task cache, result
submission, and output shape. It does not prove real Codex Desktop IPC.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

from node_bridge_testkit.node_adapter import http_json
from node_bridge_testkit.relay import make_server


def parse_stdout(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    if not text:
        return {}
    return json.loads(text[text.find("{"):text.rfind("}") + 1])


def main() -> int:
    token = "node-b-relay-ipc-preflight-token"
    server = make_server("127.0.0.1", 0, quiet=True, token=token)
    host, port = server.server_address
    relay = f"http://{host}:{port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    root = Path(tempfile.mkdtemp(prefix="node_b_relay_ipc_client_"))
    try:
        created = http_json(
            "POST",
            f"{relay}/tasks",
            {
                "target_node": "node-b",
                "task_type": "reply_exactly",
                "payload": {
                    "marker": "NODEB-RELAY-IPC-PREFLIGHT-001",
                    "text": "NODEB_RELAY_IPC_PREFLIGHT_OK_001",
                },
            },
            token=token,
        )
        task_id = str((created.get("task") or {}).get("task_id") or "")
        completed = subprocess.run(
            [
                sys.executable,
                "run_node_b_relay_ipc_client.py",
                "--relay-url",
                relay,
                "--token",
                token,
                "--node-id",
                "node-b",
                "--install-dir",
                str(root),
                "--dry-run-ipc",
                "--quiet",
            ],
            cwd=Path(__file__).resolve().parent,
            text=True,
            capture_output=True,
            check=False,
        )
        client = parse_stdout(completed.stdout)
        task_status = http_json("GET", f"{relay}/tasks/{task_id}", token=token)
        task = task_status.get("task") if isinstance(task_status.get("task"), dict) else {}
        result = task.get("result") if isinstance(task.get("result"), dict) else {}
        ok = (
            completed.returncode == 0
            and client.get("ok") is True
            and task.get("status") == "completed"
            and result.get("agent_message") == "NODEB_RELAY_IPC_PREFLIGHT_OK_001"
            and result.get("task_sent_to_codex") is True
            and result.get("codex_exact_reply_observed") is True
            and result.get("execution") == "node_b_relay_to_codex_ipc_start_turn"
        )
        print(json.dumps({
            "ok": ok,
            "relay": relay,
            "task_id": task_id,
            "client_claim": client.get("claim"),
            "relay_status": task.get("status"),
            "agent_message": result.get("agent_message"),
            "execution": result.get("execution"),
            "dry_run_ipc": True,
            "claim": "node_b_relay_ipc_client_glue_preflight_passed" if ok else "node_b_relay_ipc_client_glue_preflight_failed",
            "cannot_claim": [
                "real_codex_ipc",
                "codex_desktop_reply",
                "formal_ack",
                "external_send",
                "file_execution",
                "persistent_service",
                "long_running_autonomy",
                "production_ready_connection",
            ],
        }, ensure_ascii=False, indent=2))
        return 0 if ok else 1
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
