#!/usr/bin/env python3
"""Summarize local Node-C loop readiness without contacting the relay or Codex."""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
from typing import Any

from node_bridge_testkit.avatar_runtime import DEFAULT_INSTALL_DIR, read_json, resolve_install_dir
from run_node_c_connection_state import age_seconds, decide_state, list_cache


CANNOT_CLAIM = [
    "real_codex_ipc",
    "task_sent_to_codex",
    "codex_reply_read",
    "frontstage_auto_injection",
    "formal_ack",
    "external_send",
    "file_execution",
    "persistent_service",
    "long_running_autonomy",
    "production_ready_connection",
]


def load_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return read_json(path)
    except Exception:
        return {"error": "invalid_json", "path": str(path)}


def approval_gate_seen(root: Path) -> bool:
    cache_dir = root / "task_cache"
    if not cache_dir.exists():
        return False
    for path in cache_dir.glob("*.json"):
        try:
            record = read_json(path)
        except Exception:
            continue
        task = record.get("task")
        payload = task.get("payload") if isinstance(task, dict) else None
        result = record.get("result")
        if isinstance(result, dict) and isinstance(result.get("approval_gate"), dict):
            return True
        if not isinstance(payload, dict):
            continue
        content_b64 = payload.get("content_b64")
        if isinstance(content_b64, str):
            try:
                raw = base64.b64decode(content_b64.encode("ascii"), validate=True)
                package = json.loads(raw.decode("utf-8"))
            except Exception:
                package = None
            if isinstance(package, dict) and isinstance(package.get("approval_gate"), dict):
                return True
        filename = str(payload.get("filename") or "")
        if "approval_gate" in filename:
            return True
    return False


def build_loop_readiness(root: Path) -> dict[str, Any]:
    config_path = root / "config.json"
    state_path = root / "state.json"
    binding_path = root / "session_binding.json"
    config = load_optional_json(config_path) or {}
    state = load_optional_json(state_path) or {}
    binding = load_optional_json(binding_path)
    cache = list_cache(root)

    config_exists = config_path.exists() and "error" not in config
    state_exists = state_path.exists() and "error" not in state
    heartbeat_age = age_seconds(state.get("last_heartbeat_at")) if isinstance(state, dict) else None
    heartbeat_fresh = heartbeat_age is not None and heartbeat_age <= 120
    connection_state = decide_state(config_exists, state, binding if isinstance(binding, dict) else None, cache)
    by_status = cache.get("by_status") or {}
    pending_count = (
        int(by_status.get("pulled", 0))
        + int(by_status.get("queued", 0))
        + int(by_status.get("ready", 0))
    )
    busy = int(by_status.get("in_progress", 0)) > 0 or connection_state == "busy"
    zombie = bool(isinstance(binding, dict) and binding.get("zombie")) or connection_state == "zombie"
    session_bound = bool(isinstance(binding, dict) and binding.get("conversation_id"))

    checks = {
        "avatar_installed": config_exists and state_exists,
        "heartbeat_fresh": heartbeat_fresh,
        "task_cache_accessible": (root / "task_cache").exists(),
        "pending_task_seen": pending_count > 0,
        "no_busy_task": not busy,
        "session_bound": session_bound,
        "session_not_zombie": not zombie,
        "approval_gate_seen": approval_gate_seen(root),
    }
    if not checks["avatar_installed"]:
        readiness = "not_installed"
    elif zombie:
        readiness = "blocked_zombie_session"
    elif busy:
        readiness = "busy"
    elif heartbeat_fresh and pending_count > 0 and checks["approval_gate_seen"]:
        readiness = "local_loop_ready"
    elif heartbeat_fresh:
        readiness = "paired_no_pending_task"
    else:
        readiness = "installed_stale_or_unpaired"

    return {
        "ok": readiness == "local_loop_ready",
        "readiness": readiness,
        "install_dir": str(root),
        "node_id": (
            state.get("node_id") or config.get("node_id")
            if isinstance(state, dict) and isinstance(config, dict)
            else None
        ),
        "connection_state": connection_state,
        "heartbeat_age_seconds": heartbeat_age,
        "pending_task_count": pending_count,
        "checks": checks,
        "task_cache": cache,
        "session": {
            "bound": session_bound,
            "conversation_id": binding.get("conversation_id") if isinstance(binding, dict) else None,
            "zombie": zombie,
            "runtime_status": binding.get("runtime_status") if isinstance(binding, dict) else None,
        },
        "claim": "node_c_local_loop_readiness_observed",
        "cannot_claim": CANNOT_CLAIM,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Show local Node-C loop readiness.")
    parser.add_argument("--install-dir", default=DEFAULT_INSTALL_DIR)
    args = parser.parse_args()

    root = resolve_install_dir(args.install_dir)
    result = build_loop_readiness(root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
