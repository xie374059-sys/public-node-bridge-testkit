#!/usr/bin/env python3
"""Run a local collaborative bridge UI shell preflight."""

from __future__ import annotations

import json
import socket
import threading
import time
from urllib.request import urlopen

from node_bridge_testkit.relay import make_server


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def read_text(url: str) -> str:
    with urlopen(url, timeout=10) as response:
        return response.read().decode("utf-8")


def main() -> int:
    port = free_port()
    server = make_server("127.0.0.1", port, quiet=True)
    relay_url = f"http://127.0.0.1:{port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)

    try:
        controller_zh = read_text(f"{relay_url}/controller?lang=zh")
        host_en = read_text(f"{relay_url}/host?lang=en")
        if "控制端" not in controller_zh:
            raise AssertionError("controller zh page is missing Chinese role label")
        if "Host Console" not in host_en:
            raise AssertionError("host en page is missing Host Console title")
        if "Language" not in host_en:
            raise AssertionError("host en page is missing English language label")
        if "data-role=\"controller\"" not in controller_zh:
            raise AssertionError("controller page is missing role marker")
        if "data-role=\"host\"" not in host_en:
            raise AssertionError("host page is missing role marker")

        print(json.dumps({
            "ok": True,
            "relay": relay_url,
            "claim": "collaborative_bridge_ui_shell_passed",
            "cannot_claim": [
                "task_submission_ui",
                "host_approval_ui",
                "real_codex_ipc",
                "remote_desktop_control",
                "production_ready_ui",
            ],
        }, ensure_ascii=False, indent=2))
        return 0
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
