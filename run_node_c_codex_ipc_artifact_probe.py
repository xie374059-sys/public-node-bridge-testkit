#!/usr/bin/env python3
"""Read-only Windows Codex IPC artifact discovery.

This probe lists named-pipe names and shallow Codex/OpenAI directory entries. It
does not read file contents, send tasks, use the input box, or connect to pipes.
"""

from __future__ import annotations

import json
import platform
import subprocess


def run_powershell(command: str, timeout: float = 20.0) -> dict[str, object]:
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            timeout=timeout,
            check=False,
            text=True,
            capture_output=True,
        )
        return {
            "returncode": completed.returncode,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
        }
    except Exception as exc:
        return {"returncode": None, "stdout": "", "stderr": str(exc)}


def main() -> int:
    if platform.system().lower() != "windows":
        print(json.dumps({
            "ok": False,
            "platform": platform.system(),
            "stage": "platform",
            "error": "codex_ipc_artifact_probe_is_windows_only",
            "claim": "node_c_codex_ipc_artifact_probe_not_run",
            "cannot_claim": [
                "codex_desktop_ipc_found",
                "thread_follower_start_turn_found",
                "task_sent_to_codex",
                "codex_reply_read",
            ],
        }, ensure_ascii=False, indent=2))
        return 1

    command = r"""
$pipes = @(Get-ChildItem \\.\pipe\ -ErrorAction SilentlyContinue |
  Where-Object { $_.Name -match 'codex|openai|chatgpt' } |
  Select-Object -First 50 Name)
$roots = @(
  "$env:USERPROFILE\.codex",
  "$env:LOCALAPPDATA\OpenAI",
  "$env:APPDATA\OpenAI"
)
$entries = @()
foreach ($root in $roots) {
  if ($root -and (Test-Path $root)) {
    Get-ChildItem -Path $root -Force -ErrorAction SilentlyContinue |
      Select-Object -First 80 Name,FullName,PSIsContainer,Length,LastWriteTime |
      ForEach-Object {
        $entries += [PSCustomObject]@{
          root=$root
          name=$_.Name
          path=$_.FullName
          is_dir=$_.PSIsContainer
          length=$_.Length
          last_write_time=$_.LastWriteTime
        }
      }
  }
}
[PSCustomObject]@{
  named_pipes = $pipes
  shallow_entries = $entries
} | ConvertTo-Json -Depth 5
"""
    result = run_powershell(command)
    raw = str(result.get("stdout") or "").strip()
    parsed: dict[str, object] = {}
    if raw:
        try:
            value = json.loads(raw)
            if isinstance(value, dict):
                parsed = value
        except json.JSONDecodeError:
            parsed = {"raw": raw[-2000:], "parse_error": "json_decode_failed"}

    named_pipes = parsed.get("named_pipes") or []
    shallow_entries = parsed.get("shallow_entries") or []
    if isinstance(named_pipes, dict):
        named_pipes = [named_pipes]
    if isinstance(shallow_entries, dict):
        shallow_entries = [shallow_entries]

    pipe_hint_found = bool(named_pipes)
    artifact_hint_found = bool(shallow_entries)
    print(json.dumps({
        "ok": pipe_hint_found or artifact_hint_found,
        "platform": "Windows",
        "pipe_hint_found": pipe_hint_found,
        "artifact_hint_found": artifact_hint_found,
        "named_pipes": named_pipes if isinstance(named_pipes, list) else [],
        "shallow_entries": shallow_entries if isinstance(shallow_entries, list) else [],
        "claim": "node_c_codex_ipc_artifact_hints_found" if (pipe_hint_found or artifact_hint_found) else "node_c_codex_ipc_artifact_no_hints",
        "cannot_claim": [
            "codex_desktop_ipc_found",
            "thread_follower_start_turn_found",
            "task_sent_to_codex",
            "codex_reply_read",
            "frontstage_auto_injection",
            "input_box_automation",
            "formal_ack",
            "external_send",
            "file_execution",
        ],
    }, ensure_ascii=False, indent=2))
    return 0 if pipe_hint_found or artifact_hint_found else 1


if __name__ == "__main__":
    raise SystemExit(main())
