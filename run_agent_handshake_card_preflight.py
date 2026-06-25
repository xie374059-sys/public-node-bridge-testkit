#!/usr/bin/env python3
"""Validate that the Yuanjie handshake card format can configure connect_node."""

from __future__ import annotations

import json

from connect_node import parse_connect_card


def main() -> int:
    card = """YUANJIE_HANDSHAKE_V1
session_id=yj_test_001
relay=http://127.0.0.1:8765
node_id=node-c
role=external_node
connect_code=test-token
capabilities=reply_exactly,file_deliver,task_package
boundary=no_shell,no_file_execution,no_external_send,no_formal_ack
expires_at=2099-01-01T00:00:00+00:00
"""
    parsed = parse_connect_card(card)
    ok = (
        parsed.get("relay") == "http://127.0.0.1:8765"
        and parsed.get("node_id") == "node-c"
        and parsed.get("connect_code") == "test-token"
        and "task_package" in parsed.get("capabilities", "")
        and "no_external_send" in parsed.get("boundary", "")
    )
    print(json.dumps({
        "ok": ok,
        "parsed": parsed,
        "claim": "agent_handshake_card_parse_preflight_passed" if ok else "agent_handshake_card_parse_preflight_failed",
        "cannot_claim": [
            "qr_code_created",
            "agent_qr_read",
            "real_codex_ipc",
            "formal_ack",
            "external_send",
            "production_ready_connection",
        ],
    }, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
