#!/usr/bin/env python3
"""Check whether Codex Desktop is visible on the local Windows desktop.

This is a read-only preflight. It enumerates visible window titles and looks for
"Codex" by default. It does not click, type, inject, send a task, or read a
Codex conversation.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import platform
from ctypes import wintypes


def enum_windows_titles() -> list[dict[str, str | int]]:
    user32 = ctypes.windll.user32
    titles: list[dict[str, str | int]] = []

    enum_windows = user32.EnumWindows
    enum_windows_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    is_window_visible = user32.IsWindowVisible
    get_window_text_length = user32.GetWindowTextLengthW
    get_window_text = user32.GetWindowTextW
    get_window_thread_process_id = user32.GetWindowThreadProcessId

    def callback(hwnd: int, _lparam: int) -> bool:
        if not is_window_visible(hwnd):
            return True
        length = get_window_text_length(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        get_window_text(hwnd, buffer, length + 1)
        title = buffer.value.strip()
        if not title:
            return True
        pid = wintypes.DWORD()
        get_window_thread_process_id(hwnd, ctypes.byref(pid))
        titles.append({"hwnd": int(hwnd), "pid": int(pid.value), "title": title})
        return True

    enum_windows(enum_windows_proc(callback), 0)
    return titles


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Codex Desktop visible-window preflight.")
    parser.add_argument("--match", default="codex")
    args = parser.parse_args()

    if platform.system().lower() != "windows":
        print(json.dumps({
            "ok": False,
            "platform": platform.system(),
            "stage": "platform",
            "error": "desktop_visible_preflight_is_windows_only",
            "claim": "node_c_desktop_visible_preflight_not_run",
            "cannot_claim": [
                "codex_desktop_visible",
                "codex_desktop_ipc",
                "frontstage_auto_injection",
                "task_sent_to_codex",
                "codex_reply_read",
            ],
        }, ensure_ascii=False, indent=2))
        return 1

    titles = enum_windows_titles()
    needle = args.match.lower()
    matches = [item for item in titles if needle in str(item["title"]).lower()]
    ok = bool(matches)
    print(json.dumps({
        "ok": ok,
        "platform": "Windows",
        "match": args.match,
        "matches": matches,
        "visible_window_count": len(titles),
        "claim": "node_c_codex_desktop_visible_preflight_passed" if ok else "node_c_codex_desktop_visible_preflight_no_match",
        "cannot_claim": [
            "codex_desktop_ipc",
            "frontstage_auto_injection",
            "task_sent_to_codex",
            "codex_reply_read",
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
