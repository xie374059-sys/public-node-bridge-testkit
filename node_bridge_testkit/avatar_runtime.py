#!/usr/bin/env python3
"""Portable Node-C avatar runtime helpers.

The runtime stores only local testkit state in the project directory. It does
not read private files, execute shell commands, send messages, or connect to
private infrastructure.
"""

from __future__ import annotations

import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from node_bridge_testkit.node_adapter import DENIED_CAPABILITIES


DEFAULT_INSTALL_DIR = ".node_c_avatar"
DEFAULT_NODE_ID = "node-c"
ALLOWED_TASK_TYPES = ["reply_exactly", "file_deliver", "task_package"]
CAPABILITIES = [
    "health",
    "heartbeat",
    "capabilities",
    "reply_exactly",
    "sandbox_file_receive",
    "allowlisted_task_package_execution",
    "structured_result",
]


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def resolve_install_dir(path: str | Path = DEFAULT_INSTALL_DIR) -> Path:
    return Path(path).expanduser().resolve()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_config(node_id: str, install_dir: Path) -> dict[str, Any]:
    return {
        "schema": "node_c_avatar_config_v0.1",
        "node_id": node_id,
        "install_dir": str(install_dir),
        "created_at": now_utc(),
        "runtime": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "capabilities": CAPABILITIES,
        "allowed_task_types": ALLOWED_TASK_TYPES,
        "denied_capabilities": DENIED_CAPABILITIES,
        "boundary": {
            "local_only": True,
            "private_endpoint_routing": False,
            "external_send": False,
            "formal_ack": False,
            "file_execution": False,
            "shell_execution": False,
            "sandbox_file_write": True,
            "task_package_execution": "allowlist_only",
        },
    }


def install_avatar(node_id: str = DEFAULT_NODE_ID, install_dir: str | Path = DEFAULT_INSTALL_DIR) -> dict[str, Any]:
    root = resolve_install_dir(install_dir)
    config = build_config(node_id, root)
    write_json(root / "config.json", config)
    state = {
        "schema": "node_c_avatar_state_v0.1",
        "node_id": node_id,
        "installed": True,
        "installed_at": config["created_at"],
        "last_heartbeat_at": None,
        "last_run_claim": None,
    }
    write_json(root / "state.json", state)
    return {
        "ok": True,
        "installed": True,
        "node_id": node_id,
        "install_dir": str(root),
        "config_path": str(root / "config.json"),
        "state_path": str(root / "state.json"),
        "claim": "node_c_avatar_installed_local",
        "cannot_claim": [
            "real_codex_ipc",
            "external_node_connected",
            "formal_ack",
            "external_send",
            "file_execution",
            "long_running_autonomy",
        ],
    }


def load_avatar(install_dir: str | Path = DEFAULT_INSTALL_DIR) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    root = resolve_install_dir(install_dir)
    config_path = root / "config.json"
    state_path = root / "state.json"
    if not config_path.exists() or not state_path.exists():
        raise FileNotFoundError(f"Node-C avatar is not installed at {root}")
    return root, read_json(config_path), read_json(state_path)


def health_packet(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "node_id": config["node_id"],
        "status": "installed_local",
        "heartbeat_at": now_utc(),
        "capabilities": config["capabilities"],
        "allowed_task_types": config["allowed_task_types"],
        "denied_capabilities": config["denied_capabilities"],
        "boundary": config["boundary"],
    }


def update_state(root: Path, state: dict[str, Any], claim: str) -> dict[str, Any]:
    updated = dict(state)
    updated["last_heartbeat_at"] = now_utc()
    updated["last_run_claim"] = claim
    write_json(root / "state.json", updated)
    return updated
