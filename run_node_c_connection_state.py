#!/usr/bin/env python3
"""Summarize Node-C local connection state.

This is a local sensor. It reads only the testkit avatar sandbox and reports a
Bluetooth-like state: disconnected, discovered, paired, bound, ready, busy, or
zombie. It does not contact the relay, Codex IPC, or the input box.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from node_bridge_testkit.avatar_runtime import DEFAULT_INSTALL_DIR, read_json, resolve_install_dir


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def age_seconds(value: str | None) -> float | None:
    parsed = parse_time(value)
    if parsed is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds())


def list_cache(root: Path) -> dict[str, Any]:
    cache_dir = root / "task_cache"
    if not cache_dir.exists():
        return {"count": 0, "by_status": {}, "latest": None}
    by_status: dict[str, int] = {}
    latest: dict[str, Any] | None = None
    latest_mtime = 0.0
    count = 0
    for path in cache_dir.glob("*.json"):
        try:
            record = read_json(path)
        except Exception:
            continue
        count += 1
        status = str(record.get("status") or "unknown")
        by_status[status] = by_status.get(status, 0) + 1
        mtime = path.stat().st_mtime
        if mtime >= latest_mtime:
            latest_mtime = mtime
            latest = {
                "path": str(path),
                "task_id": record.get("task_id"),
                "task_type": record.get("task_type"),
                "marker": record.get("marker"),
                "status": status,
                "updated_at": record.get("updated_at"),
            }
    return {"count": count, "by_status": by_status, "latest": latest}


def decide_state(config_exists: bool, state: dict[str, Any], binding: dict[str, Any] | None, cache: dict[str, Any]) -> str:
    if not config_exists:
        return "disconnected"
    if binding and binding.get("zombie"):
        return "zombie"
    by_status = cache.get("by_status") or {}
    if by_status.get("in_progress", 0) > 0:
        return "busy"
    if binding and binding.get("conversation_id"):
        return "ready"
    if state.get("last_heartbeat_at"):
        return "paired"
    return "discovered"


def main() -> int:
    parser = argparse.ArgumentParser(description="Show local Node-C connection state.")
    parser.add_argument("--install-dir", default=DEFAULT_INSTALL_DIR)
    args = parser.parse_args()

    root = resolve_install_dir(args.install_dir)
    config_path = root / "config.json"
    state_path = root / "state.json"
    binding_path = root / "session_binding.json"
    config_exists = config_path.exists()
    state = read_json(state_path) if state_path.exists() else {}
    binding = read_json(binding_path) if binding_path.exists() else None
    cache = list_cache(root)
    connection_state = decide_state(config_exists, state, binding, cache)
    heartbeat_age = age_seconds(state.get("last_heartbeat_at"))

    print(json.dumps({
        "ok": config_exists,
        "connection_state": connection_state,
        "install_dir": str(root),
        "node_id": state.get("node_id") or (binding or {}).get("node_id"),
        "heartbeat_fresh": heartbeat_age is not None and heartbeat_age <= 120,
        "heartbeat_age_seconds": heartbeat_age,
        "session_bound": bool(binding and binding.get("conversation_id")),
        "conversation_id": (binding or {}).get("conversation_id"),
        "session_zombie": bool(binding and binding.get("zombie")),
        "runtime_status": (binding or {}).get("runtime_status") if binding else None,
        "task_cache": cache,
        "claim": "node_c_local_connection_state_observed" if config_exists else "node_c_local_connection_state_not_installed",
        "cannot_claim": [
            "real_codex_ipc",
            "task_sent_to_codex",
            "codex_reply_read",
            "formal_ack",
            "external_send",
            "file_execution",
            "persistent_service",
            "long_running_autonomy",
            "production_ready_connection",
        ],
    }, ensure_ascii=False, indent=2))
    return 0 if config_exists else 1


if __name__ == "__main__":
    raise SystemExit(main())
