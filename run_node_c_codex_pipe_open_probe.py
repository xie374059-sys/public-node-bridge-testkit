#!/usr/bin/env python3
"""Read-only-ish Windows probe for opening the Codex named pipe.

The probe attempts to open an existing named pipe path with read/write access,
then immediately closes it. It sends no payload and does not read conversations,
use the input box, click, paste, or press keys.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import platform
from ctypes import wintypes


GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = -1


def main() -> int:
    parser = argparse.ArgumentParser(description="Open an existing Codex named pipe without sending payload.")
    parser.add_argument("--pipe", default=r"\\.\pipe\codex-ipc")
    args = parser.parse_args()

    if platform.system().lower() != "windows":
        print(json.dumps({
            "ok": False,
            "platform": platform.system(),
            "stage": "platform",
            "error": "codex_pipe_open_probe_is_windows_only",
            "claim": "node_c_codex_pipe_open_probe_not_run",
            "cannot_claim": [
                "codex_desktop_ipc_usable",
                "thread_follower_start_turn_found",
                "task_sent_to_codex",
                "codex_reply_read",
            ],
        }, ensure_ascii=False, indent=2))
        return 1

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    handle = create_file(
        args.pipe,
        GENERIC_READ | GENERIC_WRITE,
        0,
        None,
        OPEN_EXISTING,
        0,
        None,
    )
    opened = int(handle) != INVALID_HANDLE_VALUE
    error_code = 0
    if opened:
        close_handle(handle)
    else:
        error_code = ctypes.get_last_error()

    print(json.dumps({
        "ok": opened,
        "platform": "Windows",
        "pipe": args.pipe,
        "opened": opened,
        "windows_error_code": error_code,
        "claim": "node_c_codex_pipe_opened_no_payload" if opened else "node_c_codex_pipe_open_failed",
        "cannot_claim": [
            "codex_desktop_ipc_usable",
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
    return 0 if opened else 1


if __name__ == "__main__":
    raise SystemExit(main())
