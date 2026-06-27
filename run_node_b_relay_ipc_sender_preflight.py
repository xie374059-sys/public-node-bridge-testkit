#!/usr/bin/env python3
"""Local preflight for the Node-B relay IPC sender plus dry-run client."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

from node_bridge_testkit.relay import make_server


def parse_stdout(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    if not text:
        return {}
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start:end + 1])
    return {}


def main() -> int:
    token = "node-b-relay-ipc-sender-preflight-token"
    server = make_server("127.0.0.1", 0, quiet=True, token=token)
    host, port = server.server_address
    relay = f"http://{host}:{port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    root = Path(tempfile.mkdtemp(prefix="node_b_relay_ipc_sender_"))
    script_dir = Path(__file__).resolve().parent
    try:
        sender = subprocess.Popen(
            [
                sys.executable,
                "send_node_b_relay_ipc_probe.py",
                "--relay-url",
                relay,
                "--token",
                token,
                "--node-id",
                "node-b",
                "--timeout",
                "20",
                "--interval",
                "0.2",
            ],
            cwd=script_dir,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        client = subprocess.run(
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
                "--timeout",
                "10",
                "--interval",
                "0.2",
            ],
            cwd=script_dir,
            text=True,
            capture_output=True,
            check=False,
        )
        sender_stdout, sender_stderr = sender.communicate(timeout=10)
        sender_json = parse_stdout(sender_stdout)
        client_json = parse_stdout(client.stdout)
        ok = (
            sender.returncode == 0
            and client.returncode == 0
            and sender_json.get("ok") is True
            and client_json.get("ok") is True
            and sender_json.get("task_sent_to_codex") is True
            and sender_json.get("codex_exact_reply_observed") is True
            and sender_json.get("completion_observed") is True
        )
        print(json.dumps({
            "ok": ok,
            "relay": relay,
            "sender_claim": sender_json.get("claim"),
            "client_claim": client_json.get("claim"),
            "agent_message": sender_json.get("agent_message"),
            "execution": sender_json.get("execution"),
            "dry_run_ipc": True,
            "claim": "node_b_relay_ipc_sender_preflight_passed" if ok else "node_b_relay_ipc_sender_preflight_failed",
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
            "debug": {
                "sender_returncode": sender.returncode,
                "client_returncode": client.returncode,
                "sender_stderr_tail": sender_stderr[-500:] if sender_stderr else "",
                "client_stderr_tail": client.stderr[-500:] if client.stderr else "",
            },
        }, ensure_ascii=False, indent=2))
        return 0 if ok else 1
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
