#!/usr/bin/env python3
"""Detect and optionally run a tiny Codex CLI probe.

This is a local, user-invoked preflight. It does not connect to Codex Desktop
IPC, does not execute received files, and does not send external messages.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


EXPECTED = "NODEC_CODEX_CLI_OK_001"
PROMPT = f"Reply exactly: {EXPECTED}"


def run_command(args: list[str], timeout: float = 30.0, cwd: str | None = None) -> dict[str, object]:
    try:
        completed = subprocess.run(
            args,
            cwd=cwd,
            timeout=timeout,
            check=False,
            text=True,
            capture_output=True,
        )
        return {
            "returncode": completed.returncode,
            "stdout": completed.stdout.strip()[-2000:],
            "stderr": completed.stderr.strip()[-2000:],
        }
    except subprocess.TimeoutExpired:
        return {"returncode": None, "stdout": "", "stderr": "timeout"}
    except Exception as exc:
        return {"returncode": None, "stdout": "", "stderr": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a safe Node-C Codex CLI preflight.")
    parser.add_argument("--execute", action="store_true", help="Run a tiny codex exec prompt after detection.")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    codex_path = shutil.which("codex")
    version = run_command(["codex", "--version"], timeout=15.0) if codex_path else {}
    detection_ok = bool(codex_path and version.get("returncode") == 0)
    result: dict[str, object] = {
        "ok": detection_ok,
        "stage": "detect",
        "codex_path": codex_path or "",
        "version_stdout": version.get("stdout", ""),
        "version_stderr": version.get("stderr", ""),
        "claim": "node_c_codex_cli_detected" if detection_ok else "node_c_codex_cli_not_detected",
        "cannot_claim": [
            "codex_desktop_ipc",
            "formal_ack",
            "external_send",
            "file_execution",
            "persistent_service",
            "long_running_autonomy",
        ],
    }

    if not detection_ok or not args.execute:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if detection_ok else 1

    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / "codex_last_message.txt"
        command = [
            "codex",
            "exec",
            "--skip-git-repo-check",
            "--ignore-user-config",
            "--sandbox",
            "read-only",
            "--output-last-message",
            str(out_path),
            PROMPT,
        ]
        executed = run_command(command, timeout=args.timeout, cwd=tmp)
        last_message = out_path.read_text(encoding="utf-8").strip() if out_path.exists() else ""
        ok = executed.get("returncode") == 0 and last_message == EXPECTED
        result.update({
            "ok": ok,
            "stage": "execute",
            "expected": EXPECTED,
            "last_message": last_message,
            "returncode": executed.get("returncode"),
            "stdout_tail": executed.get("stdout"),
            "stderr_tail": executed.get("stderr"),
            "claim": "node_c_codex_cli_exact_reply_passed" if ok else "node_c_codex_cli_exact_reply_failed",
        })
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
