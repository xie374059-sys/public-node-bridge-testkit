#!/usr/bin/env python3
"""Install the local-only Node-C avatar test runtime."""

from __future__ import annotations

import argparse
import json

from node_bridge_testkit.avatar_runtime import DEFAULT_INSTALL_DIR, DEFAULT_NODE_ID, install_avatar


def main() -> int:
    parser = argparse.ArgumentParser(description="Install the local-only Node-C avatar runtime.")
    parser.add_argument("--node-id", default=DEFAULT_NODE_ID)
    parser.add_argument("--install-dir", default=DEFAULT_INSTALL_DIR)
    args = parser.parse_args()

    result = install_avatar(node_id=args.node_id, install_dir=args.install_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
