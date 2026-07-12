# Aethereal Mobile Backup Appliance

## Implementation Plan

**Version:** 0.1  
**Aligned PRD:** Aethereal Mobile Backup Appliance PRD v0.2  
**Target platform:** Raspberry Pi 4  
**Primary implementation language:** Python 3

---

# 1. Purpose

This document defines the implementation approach for the Aethereal Mobile Backup Appliance.

The implementation shall preserve the product principle defined in the PRD:

> Backup correctness has priority over copy speed.

The design shall ensure that the source remains read-only, destination capacity is validated before copy, copied files are verified, and interrupted jobs can be recovered without presenting incomplete files as valid backups.

---

# 2. Recommended Technology Stack

## 2.1 Operating System

Use Raspberry Pi OS with Desktop.

Reasons:

- Supports a graphical desktop for VNC administration.
- Provides standard Linux storage, udev, systemd, networking, and filesystem tools.
- Allows the backup services to operate independently of the graphical desktop.

The graphical desktop shall not be part of the critical backup path.

---

## 2.2 Application Runtime

Use Python 3.

Recommended libraries and components:

- `FastAPI` for the local HTTP API.
- `uvicorn` for the application server.
- `sqlite3` or SQLAlchemy Core for SQLite persistence.
- `asyncio` for service coordination and WebSocket event delivery.
- `hashlib` for SHA-256.
- `pathlib` for path handling.
- `psutil` for process and host telemetry where appropriate.
- `pyudev` for Linux device event monitoring.
- `gpiozero` or an equivalent GPIO abstraction for LED control.

The backup engine shall not execute inside a FastAPI request worker.

---

# 3. Process Architecture

Implement four primary services.

```text
+---------------------+
| backupd             |
|                     |
| media detection     |
| mount orchestration |
| preflight           |
| copy                |
| verify              |
| recovery            |
+----------+----------+
           |
           | SQLite + event stream
           |
+----------+----------+      +----------------------+
| webapp              |      | led-status           |
|                     |      |                      |
| REST API            |      | state consumer       |
| WebSocket           |      | LED pattern engine   |
| mobile web UI       |      +----------------------+
+---------------------+
           |
           |
+----------+----------+
| system-watch        |
|                     |
| power telemetry     |
| thermal telemetry   |
| system disk checks  |
+---------------------+
```

Suggested systemd service names:

```text
aethereal-backupd.service
aethereal-web.service
aethereal-led.service
aethereal-watch.service
```

---

# 4. Repository Structure

Recommended repository layout:

```text
aethereal-backup/
|
+-- pyproject.toml
+-- README.md
+-- config/
|   +-- default.yaml
|
+-- src/
|   +-- aethereal/
|       +-- common/
|       |   +-- config.py
|       |   +-- logging.py
|       |   +-- models.py
|       |   +-- errors.py
|       |
|       +-- db/
|       |   +-- connection.py
|       |   +-- schema.py
|       |   +-- migrations/
|       |
|       +-- backup/
|       |   +-- service.py
|       |   +-- state_machine.py
|       |   +-- devices.py
|       |   +-- mount.py
|       |   +-- inventory.py
|       |   +-- identity.py
|       |   +-- preflight.py
|       |   +-- planner.py
|       |   +-- copier.py
|       |   +-- verifier.py
|       |   +-- recovery.py
|       |   +-- cancellation.py
|       |
|       +-- web/
|       |   +-- app.py
|       |   +-- api/
|       |   +-- websocket.py
|       |   +-- auth.py
|       |   +-- static/
|       |   +-- templates/
|       |
|       +-- led/
|       |   +-- service.py
|       |   +-- patterns.py
|       |   +-- gpio.py
|       |
|       +-- watch/
|           +-- service.py
|           +-- thermal.py
|           +-- power.py
|           +-- storage.py
|
+-- systemd/
|   +-- aethereal-backupd.service
|   +-- aethereal-web.service
|   +-- aethereal-led.service
|   +-- aethereal-watch.service
|
+-- scripts/
|   +-- install.sh
|   +-- configure-ap.sh
|   +-- configure-vnc.sh
|   +-- migrate-db.sh
|
+-- tests/
    +-- unit/
    +-- integration/
    +-- fault/
    +-- system/
```

---

# 5. Configuration Model

Use one primary configuration file.

Suggested path:

```text
/etc/aethereal-backup/config.yaml
```

Minimum configuration fields:

```yaml
device:
  hostname: backup.local

network:
  ssid: Aethereal-Backup
  static_ip: 192.168.50.1

destination:
  filesystem_uuid: ""
  backup_root: /Backups
  safety_margin_percent: 5
  safety_margin_min_bytes: 10000000000

source:
  mount_root: /run/aethereal/source
  read_only: true

backup:
  partial_suffix: .aethereal-partial
  hash_algorithm: sha256
  verification_retries: 2
  single_active_source: true

database:
  path: /var/lib/aethereal-backup/aethereal.db

logging:
  path: /var/log/aethereal-backup
  retention_days: 30

thermal:
  warning_celsius: 75

system_storage:
  critical_free_bytes: 1000000000
```

Configuration validation shall occur before service startup.

Invalid critical configuration shall prevent `backupd` from entering READY state.

---

# 6. SQLite Schema

Use SQLite in WAL mode unless testing identifies reliability issues on the selected system storage.

Minimum schema:

## `source_volume`

```text
id
filesystem_uuid
volume_label
filesystem_type
capacity_bytes
device_identifier
device_serial
logical_name
first_seen_at
last_seen_at
```

## `backup_job`

```text
id
created_at
started_at
ended_at
source_volume_id
destination_uuid
session_path
state
files_discovered
files_planned
files_verified
files_failed
planned_bytes
copied_bytes
warning_count
error_count
```

## `preflight`

```text
id
backup_job_id
created_at
source_file_count
new_file_count
already_backed_up_count
conflict_count
unreadable_count
source_bytes
new_bytes
destination_free_bytes
operational_reserve_bytes
safety_margin_bytes
required_bytes
result
```

## `source_file`

```text
id
source_volume_id
relative_path
filename
size_bytes
mtime_ns
content_identity_id
last_seen_at
```

## `content_identity`

```text
id
size_bytes
sha256
created_at
```

Create a unique index on:

```text
(size_bytes, sha256)
```

## `destination_file`

```text
id
content_identity_id
backup_job_id
relative_destination_path
verified_at
status
```

## `copy_operation`

```text
id
backup_job_id
source_file_id
destination_file_id
started_at
ended_at
bytes_written
state
attempt_number
error_code
error_message
```

## `verification_result`

```text
id
copy_operation_id
source_sha256
destination_sha256
verified_at
result
```

## `event_log`

```text
id
timestamp
severity
component
backup_job_id
event_code
message
details_json
```

All schema changes shall use explicit migrations.

---

# 7. Authoritative State Machine

Implement the backup job state machine as code, not as loosely coordinated string assignments.

Suggested approach:

```text
State enum
+
allowed transition map
+
transactional state transition function
```

Example transition rules:

```text
IDLE
  -> SOURCE_DETECTED

SOURCE_DETECTED
  -> SOURCE_MOUNTING
  -> BACKUP_FAILED

SOURCE_MOUNTING
  -> SOURCE_READY
  -> BACKUP_FAILED

SOURCE_READY
  -> PREFLIGHT_SCANNING

PREFLIGHT_SCANNING
  -> PREFLIGHT_HASHING
  -> PREFLIGHT_BLOCKED
  -> BACKUP_FAILED

PREFLIGHT_HASHING
  -> PREFLIGHT_COMPARING
  -> PREFLIGHT_BLOCKED
  -> BACKUP_FAILED

PREFLIGHT_COMPARING
  -> PREFLIGHT_CAPACITY_CHECK

PREFLIGHT_CAPACITY_CHECK
  -> PREFLIGHT_READY
  -> PREFLIGHT_WARNING
  -> PREFLIGHT_BLOCKED

PREFLIGHT_READY
  -> BACKUP_QUEUED

BACKUP_QUEUED
  -> BACKUP_COPYING

BACKUP_COPYING
  -> BACKUP_VERIFYING
  -> BACKUP_CANCELLING
  -> RECOVERY_REQUIRED
  -> BACKUP_FAILED

BACKUP_VERIFYING
  -> BACKUP_COMPLETED
  -> BACKUP_COMPLETED_WITH_WARNINGS
  -> BACKUP_CANCELLING
  -> RECOVERY_REQUIRED
  -> BACKUP_FAILED
```

Every transition shall:

1. Validate the transition.
2. Persist the new state.
3. Create an event record.
4. Publish a state event to subscribers.

---

# 8. Media Detection

Implement device detection with `pyudev`.

The media monitor shall:

1. Detect block-device insertion.
2. Enumerate partitions.
3. Determine filesystem type.
4. Obtain UUID and label.
5. Classify the device as source candidate, configured destination, or unrelated device.

Do not select devices by `/dev/sda`, `/dev/sdb`, or insertion order.

Device identity shall be based on stable metadata where available.

---

# 9. Source Mounting Strategy

The source mount path shall be controlled by the application.

Suggested root:

```text
/run/aethereal/source/<source-id>
```

Mount source media with read-only options.

The mount layer shall:

1. Detect whether the volume is already mounted.
2. Reject an unexpected writable mount.
3. Unmount or reject the existing mount according to policy.
4. Mount the source read-only.
5. Inspect `/proc/self/mountinfo` or equivalent authoritative mount information.
6. Confirm effective read-only status.
7. Only then transition to `MOUNTED_READ_ONLY`.

The backup engine shall never trust requested mount options without verifying the effective mount state.

Automatic filesystem repair shall be disabled.

---

# 10. Destination Mounting and Validation

The destination SSD shall be configured by filesystem UUID.

At service startup and before each preflight:

1. Find the configured UUID.
2. Confirm exactly one matching volume.
3. Confirm writable mount state.
4. Confirm backup root exists or can be created.
5. Confirm free capacity.
6. Confirm the filesystem is not reporting read-only state.
7. Record destination device metadata.

If validation fails, backup shall remain blocked.

---

# 11. Source Inventory

Inventory shall walk configured source roots.

For every regular file:

```text
relative_path
filename
size_bytes
mtime_ns
```

shall be collected.

Do not follow symbolic links.

Unreadable entries shall be recorded and surfaced during preflight.

Inventory shall be deterministic.

Sort paths by normalized relative path before planning.

---

# 12. Content Identity Strategy

The definitive identity is:

```text
size_bytes + SHA-256
```

Optimization:

If a source file instance matches a previously recorded tuple:

```text
source_volume_id
relative_path
size_bytes
mtime_ns
```

the previously stored content identity may be reused.

Otherwise calculate SHA-256.

Hash files in streaming chunks.

Suggested initial chunk size:

```text
8 MiB
```

Chunk size shall be configurable and performance-tested.

---

# 13. Preflight Implementation

The preflight pipeline shall be:

```text
VALIDATE SOURCE
      |
      v
VALIDATE DESTINATION
      |
      v
INVENTORY SOURCE
      |
      v
RESOLVE CONTENT IDENTITIES
      |
      v
COMPARE WITH VERIFIED DESTINATION MANIFEST
      |
      v
DETECT PATH CONFLICTS
      |
      v
CALCULATE CAPACITY
      |
      v
PERSIST PREFLIGHT
      |
      v
READY / WARNING / BLOCKED
```

Capacity calculation:

```text
required_bytes =
    new_file_bytes
    + operational_reserve_bytes
    + safety_margin_bytes
```

Safety margin:

```text
max(
    destination_capacity * configured_percent,
    configured_minimum_bytes
)
```

Initial operational reserve recommendation:

```text
max(
    largest_new_file_bytes,
    512 MiB
)
```

This formula shall be validated during implementation and documented as the v1 rule.

A dry run executes the same pipeline but does not transition into copying.

---

# 14. Backup Planning

The planner shall generate an immutable file plan for the job.

Each planned file shall contain:

```text
source_file_id
content_identity_id
source_path
destination_final_path
destination_partial_path
planned_size_bytes
classification
```

Only `NEW` files shall enter the copy queue.

`ALREADY_BACKED_UP` files shall be recorded as skipped.

`POTENTIAL_CONFLICT` shall block the job.

An unreadable required file shall block the job unless a future policy explicitly defines a warning-only mode.

For v1, treat unreadable regular files as blocking.

---

# 15. Copy Implementation

For every planned file:

1. Create the destination parent directory.
2. Confirm the final path does not exist unexpectedly.
3. Open the source read-only.
4. Open the partial destination with exclusive creation.
5. Copy data in chunks.
6. Update copied-byte progress.
7. Flush Python buffers.
8. Call `os.fsync()` on the partial destination file.
9. Transition to `COPIED_PENDING_VERIFICATION`.
10. Verify content.
11. Atomically rename the partial file to the final path.
12. `fsync()` the parent directory where supported.
13. Commit verification state in SQLite.

Use:

```text
<filename>.aethereal-partial
```

for temporary files.

Do not use `shutil.copy2()` as the entire copy abstraction without controlling flush and verification behaviour.

---

# 16. Verification Implementation

Verification is mandatory.

For each newly copied file:

1. Obtain source SHA-256.
2. Calculate destination partial-file SHA-256.
3. Compare hashes.
4. On match, finalize.
5. On mismatch, retain diagnostic state, remove or quarantine the partial according to policy, and retry.

Default retries:

```text
2 additional copy attempts
```

Recommended implementation interpretation:

```text
maximum total attempts = 3
```

The implementation shall make the distinction between retry count and total attempt count explicit.

After final failure:

```text
file state = FAILED
job cannot become BACKUP_COMPLETED
```

---

# 17. Recovery Implementation

At `backupd` startup:

1. Open SQLite.
2. Run database integrity checks appropriate for startup.
3. Find non-terminal backup jobs.
4. Inspect associated destination session directories.
5. Enumerate partial files.
6. Reconcile verified destination records.
7. Mark jobs `RECOVERY_REQUIRED`.
8. Wait for source and destination validation.
9. Run recovery preflight.
10. Resume at file level.

Recovery rules:

- Valid verified files remain complete.
- Partial files are not valid backups.
- Partial files may be deleted and recopied.
- Destination files without verified manifest state shall be reconciled conservatively.
- A different source volume shall not be substituted for the original source.

---

# 18. Cancellation

Use a cooperative cancellation token.

Cancellation flow:

1. API sets cancellation request.
2. Backup engine persists `BACKUP_CANCELLING`.
3. Planner stops dispatching new files.
4. Current file finishes or aborts at a controlled boundary.
5. Partial state is preserved as invalid.
6. SQLite state is committed.
7. Job transitions to `BACKUP_CANCELLED`.

Do not terminate the process to implement normal cancellation.

---

# 19. Event Model

Define a typed event model.

Minimum event types:

```text
SYSTEM_STATE_CHANGED
SOURCE_DETECTED
SOURCE_REMOVED
SOURCE_MOUNTED_READ_ONLY
SOURCE_PROTECTION_FAILURE
DESTINATION_VALIDATED
PREFLIGHT_STARTED
PREFLIGHT_PROGRESS
PREFLIGHT_COMPLETED
BACKUP_STARTED
FILE_COPY_STARTED
FILE_COPY_PROGRESS
FILE_COPY_COMPLETED
FILE_VERIFICATION_STARTED
FILE_VERIFICATION_COMPLETED
FILE_VERIFICATION_FAILED
BACKUP_PROGRESS
BACKUP_COMPLETED
BACKUP_FAILED
BACKUP_CANCELLED
RECOVERY_REQUIRED
RECOVERY_STARTED
RECOVERY_COMPLETED
POWER_WARNING
THERMAL_WARNING
SYSTEM_STORAGE_WARNING
```

Events shall be persisted when operationally relevant.

The web and LED services shall consume state and progress through a stable internal interface.

---

# 20. Web API

Recommended REST endpoints:

```text
GET  /api/v1/status
GET  /api/v1/source
GET  /api/v1/destination

POST /api/v1/preflight
POST /api/v1/dry-run
POST /api/v1/backups
POST /api/v1/backups/{job_id}/cancel
POST /api/v1/backups/{job_id}/resume
POST /api/v1/backups/{job_id}/retry
POST /api/v1/backups/{job_id}/verify

GET  /api/v1/backups
GET  /api/v1/backups/{job_id}

GET  /api/v1/logs

POST /api/v1/source/unmount
POST /api/v1/destination/unmount

POST /api/v1/system/reboot
POST /api/v1/system/shutdown

GET  /api/v1/system
```

WebSocket:

```text
GET /api/v1/events
```

The WebSocket shall provide real-time state and progress updates.

The REST API remains authoritative for current snapshots.

---

# 21. Web UI

Implement a mobile-first single-device interface.

Primary screens:

```text
Dashboard
Preflight / Dry Run
Active Backup
Backup History
Backup Details
Logs
System Status
Settings
```

The dashboard shall prioritize:

```text
SOURCE
DESTINATION
CURRENT STATE
PRIMARY ACTION
```

Example:

```text
Canon Card 01
Read-only

Backup SSD
1.42 TB free

47 new files
38.6 GB

[ Dry Run ]
[ Start Backup ]
```

During backup:

```text
Backing up

42%
16.2 GB / 38.6 GB

IMG_8421.CR3

Copying
128 MB/s

Estimated 3m 12s remaining

[ Cancel Backup ]
```

The UI shall not require a page reload for progress updates.

---

# 22. Authentication

For v1, implement local single-user authentication.

Recommended approach:

- One local administrator account.
- Password hash stored using a modern password-hashing algorithm.
- Secure session cookie.
- CSRF protection for state-changing browser requests.
- Session timeout.
- Re-authentication may be required for shutdown or reboot.

The application shall bind only to the intended appliance network interfaces unless explicitly configured otherwise.

---

# 23. LED Service

The LED service shall subscribe to authoritative state.

Implement each LED pattern as a reusable timing sequence.

Example abstraction:

```python
Pattern(
    steps=[
        LedOn(0.1),
        LedOff(0.1),
        LedOn(0.1),
        LedOff(2.8),
    ],
    repeat=True,
)
```

Progress overlays shall be generated from the current backup progress bucket:

```text
0-24%   = no progress blink
25-49%  = 1 blink
50-74%  = 2 blinks
75-99%  = 3 blinks
100%    = 4 blinks
```

Verification state shall override the copy progress pattern once the copy phase reaches 100%.

---

# 24. Power, Thermal, and System Monitoring

`aethereal-watch` shall poll:

```text
CPU temperature
system storage free capacity
load
memory
undervoltage telemetry when available
```

Recommended default polling interval:

```text
5 seconds
```

Warnings shall be persisted and published as events.

Persistent power-warning policy:

- Track warning duration.
- Before backup start, block automatic start if the power warning remains active beyond the configured persistence threshold.
- Do not silently classify transient historical warnings as current instability.

---

# 25. Logging

Use structured logging.

Recommended fields:

```text
timestamp
severity
component
event_code
backup_job_id
source_volume_id
message
details
```

Log to journald and optionally rotating application files.

Do not log file content.

Avoid logging authentication credentials or Wi-Fi passwords.

---

# 26. systemd Configuration

All services shall:

- Start automatically.
- Restart on unexpected failure where safe.
- Use explicit service users.
- Use restricted filesystem permissions.
- Declare startup ordering.

Suggested dependency model:

```text
network.target
      |
      v
aethereal-backupd
      |
      +--> aethereal-web
      |
      +--> aethereal-led
      |
      +--> aethereal-watch
```

The web service may start before `backupd` is ready but shall report the backend as unavailable.

The backup engine shall not depend on the web service.

---

# 27. Wi-Fi Access Point

Configure the Raspberry Pi as a standalone access point.

Implementation tasks:

1. Configure SSID.
2. Configure WPA authentication.
3. Configure static appliance IP.
4. Configure DHCP for connected clients.
5. Configure local hostname resolution.
6. Confirm the web application is reachable without internet.
7. Confirm VNC works over the access-point network.

The AP shall start automatically during boot.

---

# 28. Installation and Provisioning

Provide an idempotent installation script.

The installer shall:

1. Validate Raspberry Pi OS version.
2. Install system dependencies.
3. Create service users and directories.
4. Install the Python application.
5. Create the SQLite database.
6. Run migrations.
7. Install systemd units.
8. Configure logging.
9. Configure Wi-Fi access point.
10. Enable VNC.
11. Create initial administrator credentials.
12. Request or detect destination SSD UUID.
13. Validate hardware configuration.
14. Enable and start services.

A reinstall shall not silently delete backup history.

---

# 29. Implementation Phases

## Phase 0 - Hardware Qualification

Deliverables:

- Raspberry Pi 4 baseline.
- Qualified power source.
- Qualified SSD.
- Qualified USB SD reader.
- Cooling configuration.
- LED hardware decision.

Exit criteria:

- SSD and SD reader operate simultaneously under sustained load.
- No persistent undervoltage.
- Sustained hashing workload remains thermally acceptable.

---

## Phase 1 - Core Persistence and State Machine

Implement:

- Configuration.
- SQLite schema and migrations.
- Typed state model.
- State transition engine.
- Structured logging.
- Event model.

Exit criteria:

- State transitions are unit-tested.
- Invalid transitions are rejected.
- Job state survives restart.

---

## Phase 2 - Device Detection and Read-Only Source Mounting

Implement:

- udev monitoring.
- Source identity.
- Destination identity.
- Read-only source mount.
- Effective mount validation.

Exit criteria:

- Writable source mount blocks backup.
- Correct destination SSD is positively identified.
- Wrong USB disk is rejected.

---

## Phase 3 - Inventory, Identity, and Preflight

Implement:

- Source inventory.
- SHA-256 identity.
- Identity cache.
- Duplicate detection.
- Conflict detection.
- Capacity planning.
- Dry run.

Exit criteria:

- Dry run classifies new and already-backed-up content correctly.
- Insufficient space blocks backup.
- Same filename with different content is detected.

---

## Phase 4 - Copy and Verification Engine

Implement:

- Immutable backup plan.
- Partial-file copy.
- Durable flush.
- SHA-256 verification.
- Atomic finalization.
- Retry policy.
- Progress tracking.

Exit criteria:

- Every completed destination file is verified.
- Partial files are never marked valid.
- Hash mismatch prevents job completion.

---

## Phase 5 - Recovery and Cancellation

Implement:

- Startup recovery.
- Filesystem and SQLite reconciliation.
- File-level resume.
- Source removal handling.
- Destination removal handling.
- Cooperative cancellation.

Exit criteria:

- Power-loss tests recover correctly.
- Verified files are not recopied.
- Cancelled jobs preserve verified content.

---

## Phase 6 - Web Application

Implement:

- REST API.
- WebSocket event stream.
- Authentication.
- Mobile dashboard.
- Dry-run UI.
- Active backup UI.
- History.
- Logs.
- System status.

Exit criteria:

- Full normal workflow can be controlled from iPhone Safari.
- Backup continues after iPhone disconnect.
- Progress updates without page refresh.

---

## Phase 7 - LED and System Watcher

Implement:

- LED patterns.
- Progress overlays.
- Power monitoring.
- Thermal monitoring.
- System-storage monitoring.

Exit criteria:

- Normal field workflow can be completed without web UI.
- LED state matches web state.
- Warning conditions appear in logs and UI.

---

## Phase 8 - Appliance Provisioning

Implement:

- Wi-Fi access point.
- VNC.
- systemd services.
- Installer.
- Upgrade and migration process.

Exit criteria:

- Fresh Raspberry Pi can be provisioned repeatably.
- Appliance boots into READY without manual shell interaction.

---

## Phase 9 - Verification and Field Qualification

Execute the Verification Plan.

Exit criteria:

- All v1 acceptance criteria pass.
- No open critical or high-severity integrity defects.
- Field workflow validated with Canon and DJI media.

---

# 30. Definition of Done

Implementation is complete only when:

- The software is installable through the documented provisioning process.
- All database migrations are repeatable.
- The full PRD requirement set is traceable to implementation components.
- Automated unit and integration tests pass.
- The Verification Plan exit criteria are satisfied.
- The target hardware configuration is qualified.
- A clean appliance can execute the complete field workflow without shell access.
