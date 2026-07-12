# Aethereal Mobile Backup Appliance

Field backup engine for photography and drone media. See `PRD/` for the product,
implementation, and verification specifications.

Develop on macOS (portable core); deploy on Raspberry Pi 4 (Raspberry Pi OS, Python 3.11).

## Status

The **portable, correctness-critical core is implemented and tested** (ruff + mypy
`--strict` clean, full suite green on macOS and in the Linux container):

- Backup engine: preflight, planner, copy / three-way verify / durable finalize,
  content-addressed dedup, crash recovery, cancellation, job state machine, event bus
- SQLite destination manifest (WAL + `synchronous=FULL`) with explicit migrations
- FastAPI REST + WebSocket API and a mobile-first web UI

The **Raspberry Pi appliance layer is specified but not yet implemented**:

- Linux platform integration: udev media detection, read-only source mount + effective
  validation, ext4/UUID destination validation
- LED status service and the power/thermal/clock-trust watcher (`src/aethereal/led/`,
  `watch/`, `update/` are currently placeholder packages)
- systemd units, Wi-Fi access point, the installer, and GitHub Actions CI/CD

`PRD/` holds the full v1 **specification/target**; this repository currently implements
the portable core described above, not the complete appliance.

## Development

### macOS (portable core)

Uses [uv](https://docs.astral.sh/uv/) with Python 3.11 (matching Raspberry Pi OS Bookworm).

```sh
uv sync                       # create .venv and install deps
uv run pytest -q              # tests
uv run mypy                   # strict type check
uv run ruff check src tests   # lint
uv run python scripts/dev_server.py   # web UI + API at http://127.0.0.1:8011
```

The portable core (preflight, copy/verify, dedup, recovery, engine, web API, mobile UI)
runs and is tested on macOS.

### Linux container (matches the Raspberry Pi)

The OS-specific parts — real `POSIX_FADV_DONTNEED`, ext4 loopback mounts, and `udev`
device detection — cannot be exercised on macOS. A Debian Bookworm + Python 3.11 container
provides a faithful Linux environment on the Mac (Docker required).

```sh
docker compose build             # build the image (first time)
docker compose run --rm test     # run the full suite on real Linux
docker compose run --rm dev      # interactive shell in the container
```

The repo is bind-mounted, so edits on the Mac are picked up without rebuilding. The
container's virtualenv lives at `/opt/venv` (outside the mounted tree) so it never
collides with the host's macOS `.venv`.

For tests that create loopback ext4 filesystems and mount them (source read-only
enforcement, ext4 finalization crash windows), use the privileged service:

```sh
docker compose run --rm privileged pytest -q
```

GPIO (the `pi` optional dependency group) is Raspberry Pi hardware only and is excluded
from the container.
