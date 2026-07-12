"""Raspberry Pi runtime entrypoint: load config, build the appliance, and serve.

This is what a systemd unit runs on the Pi. It uses the real platform, device
enumeration, and mounting (Linux only).

    uv run python scripts/run_appliance.py --config /etc/aethereal-backup/config.yaml
"""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from aethereal.appliance import build_appliance
from aethereal.common.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Aethereal backup appliance")
    parser.add_argument("--config", type=Path, default=Path("/etc/aethereal-backup/config.yaml"))
    parser.add_argument("--host", default=None, help="bind address (default: config static_ip)")
    parser.add_argument("--port", type=int, default=8011)
    args = parser.parse_args()

    config = load_config(args.config)
    # SEC-006: bind only to the configured appliance address unless overridden.
    host = args.host or config.network.static_ip
    app = build_appliance(config)
    print(f"[appliance] serving on http://{host}:{args.port}")
    uvicorn.run(app, host=host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
