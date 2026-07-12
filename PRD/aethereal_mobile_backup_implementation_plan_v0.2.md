# Aethereal Mobile Backup Appliance

## Implementation Plan

**Version:** 0.2  
**Aligned PRD:** Aethereal Mobile Backup Appliance PRD v0.3  
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
- `asyncio` for orchestration and WebSocket event delivery.
- `concurrent.futures.ThreadPoolExecutor` or `asyncio.to_thread()` for blocking copy and hashing work.
- `hashlib` for SHA-256.
- `pathlib` for path handling.
- `psutil` for process and host telemetry where appropriate.
- `pyudev` for Linux device event monitoring.
- `gpiozero` or an equivalent GPIO abstraction for LED control.

The backup engine shall not execute inside a FastAPI request worker.

The asyncio event loop shall not perform large synchronous file copies or SHA-256 loops directly.

Blocking source hashing, copy, and destination verification shall run in a bounded worker pool.

Worker threads shall publish progress into the central event loop through a thread-safe event boundary.

The initial implementation shall use a bounded concurrency of one active copy file at a time, consistent with the single active source and correctness-first v1 policy.
# 3. Process Architecture

Implement four primary services.

```text
+---------------------+
| backupd             |
|                     |
| asyncio orchestrator|
| state authority     |
| device events       |
| preflight planning  |
| recovery            |
|                     |
| bounded I/O workers |
| hashing             |
| copy                |
| verify              |
+----------+----------+
           |
           | destination manifest + event IPC
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
| clock trust         |
+---------------------+
```

Suggested systemd service names:

```text
aethereal-backupd.service
aethereal-web.service
aethereal-led.service
aethereal-watch.service
```

The blocking I/O worker pool is internal to `backupd`.

The event loop remains responsive while a worker hashes or copies a large file.

`backupd` remains the sole authority for backup state.
# 4. Repository Structure

Recommended repository layout:

```text
aethereal-backup/
|
+-- pyproject.toml
+-- README.md
+-- CHANGELOG.md
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
|       |   +-- version.py
|       |
|       +-- db/
|       |   +-- appliance.py
|       |   +-- destination.py
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
|       |   +-- snapshot.py
|       |   +-- preflight.py
|       |   +-- planner.py
|       |   +-- object_store.py
|       |   +-- copier.py
|       |   +-- verifier.py
|       |   +-- finalize.py
|       |   +-- recovery.py
|       |   +-- cancellation.py
|       |   +-- workers.py
|       |
|       +-- web/
|       |   +-- app.py
|       |   +-- api/
|       |   +-- websocket.py
|       |   +-- auth.py
|       |   +-- time_sync.py
|       |   +-- static/
|       |   +-- templates/
|       |
|       +-- led/
|       |   +-- service.py
|       |   +-- patterns.py
|       |   +-- gpio.py
|       |
|       +-- watch/
|       |   +-- service.py
|       |   +-- thermal.py
|       |   +-- power.py
|       |   +-- storage.py
|       |   +-- clock.py
|       |
|       +-- update/
|           +-- service.py
|           +-- release.py
|           +-- integrity.py
|           +-- rollback.py
|
+-- packaging/
|   +-- release-manifest.json.template
|
+-- systemd/
|   +-- aethereal-backupd.service
|   +-- aethereal-web.service
|   +-- aethereal-led.service
|   +-- aethereal-watch.service
|
+-- scripts/
|   +-- install.sh
|   +-- lib/
|   |   +-- platform.sh
|   |   +-- network.sh
|   |   +-- credentials.sh
|   |   +-- storage.sh
|   |   +-- services.sh
|   |   +-- health.sh
|   +-- configure-ap.sh
|   +-- migrate-db.sh
|   +-- update.sh
|
+-- .github/
|   +-- workflows/
|   |   +-- ci.yml
|   |   +-- installer.yml
|   |   +-- hardware.yml
|   |   +-- release.yml
|   +-- dependabot.yml
|
+-- tests/
    +-- unit/
    +-- integration/
    +-- fault/
    +-- system/
    +-- installer/
```
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
  interface: wlan0

destination:
  filesystem_uuid: ""
  required_filesystem: ext4
  backup_root: /Backups
  object_store_root: /Backups/.aethereal/objects/sha256
  manifest_path: /Backups/.aethereal/manifest.sqlite3
  safety_margin_percent: 5
  safety_margin_min_bytes: 10000000000

source:
  mount_root: /run/aethereal/source
  supported_filesystems:
    - vfat
    - exfat
  block_device_read_only: true
  read_only_mount: true

backup:
  partial_suffix: .aethereal-partial
  hash_algorithm: sha256
  verification_retries: 2
  single_active_source: true
  strict_source_hashing: true
  io_worker_count: 1
  io_chunk_bytes: 8388608
  destination_cache_evict: true
  direct_io_verify: false

database:
  appliance_path: /var/lib/aethereal-backup/appliance.db
  destination_wal: true
  destination_synchronous: FULL

logging:
  path: /var/log/aethereal-backup
  retention_days: 30

thermal:
  warning_celsius: 75

time:
  require_trusted_clock: true
  rtc_profile: ds3231
  allow_phone_sync: true
  max_clock_skew_seconds: 300

system_storage:
  critical_free_bytes: 1000000000
```

Configuration validation shall occur before service startup.

Invalid critical configuration shall prevent `backupd` from entering READY state.
# 6. Persistence and SQLite Schema

Use two SQLite databases.

## Appliance-local database

Suggested path:

```text
/var/lib/aethereal-backup/appliance.db
```

This database stores non-authoritative appliance state.

Minimum tables:

### `schema_meta`

```text
schema_version
application_version
migrated_at
```

### `appliance`

```text
installation_id
created_at
installed_version
last_successful_health_check
```

### `source_alias`

```text
id
observed_identity_json
logical_name
first_seen_at
last_seen_at
```

### `system_event`

```text
id
timestamp
severity
component
event_code
message
details_json
```

## Destination manifest database

Suggested path:

```text
/Backups/.aethereal/manifest.sqlite3
```

Use:

```text
PRAGMA journal_mode=WAL
PRAGMA synchronous=FULL
```

Minimum schema:

### `schema_meta`

```text
schema_version
application_version
migrated_at
```

### `source_volume`

```text
id
filesystem_serial
volume_label
filesystem_type
capacity_bytes
partition_start
partition_size
device_identifier
device_model
device_serial
logical_name
first_seen_at
last_seen_at
```

### `source_snapshot`

```text
id
source_volume_id
snapshot_sha256
created_at
file_count
total_bytes
```

### `backup_job`

```text
id
created_at
started_at
ended_at
source_volume_id
source_snapshot_id
destination_uuid
session_path
state
files_discovered
files_planned
files_copied
files_skipped
files_verified
files_failed
planned_bytes
copied_bytes
warning_count
error_count
```

### `preflight`

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

### `source_file`

```text
id
source_snapshot_id
relative_path
filename
size_bytes
mtime_ns
content_identity_id
```

### `content_identity`

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

### `content_object`

```text
id
content_identity_id
object_path
status
pending_temp_path
pending_final_path
verified_at
```

### `session_entry`

```text
id
backup_job_id
source_file_id
content_object_id
session_path
state
created_at
```

### `copy_operation`

```text
id
backup_job_id
source_file_id
content_object_id
started_at
ended_at
bytes_written
preflight_source_sha256
copy_stream_sha256
destination_sha256
state
attempt_number
error_code
error_message
```

### `verification_result`

```text
id
copy_operation_id
preflight_source_sha256
copy_stream_sha256
destination_sha256
verified_at
result
```

### `event_log`

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

The destination manifest is authoritative for verification state on that SSD.
# 7. Authoritative State Machine

Implement the backup job state machine as code, not as loosely coordinated string assignments.

Use:

```text
State enum
+
complete allowed-transition map
+
transactional state transition function
```

Required transition coverage includes:

```text
IDLE
  -> SOURCE_DETECTED
  -> MULTIPLE_SOURCES_DETECTED

SOURCE_DETECTED
  -> SOURCE_MOUNTING
  -> SOURCE_PROTECTION_FAILURE
  -> BACKUP_FAILED

MULTIPLE_SOURCES_DETECTED
  -> SOURCE_DETECTED
  -> IDLE

SOURCE_MOUNTING
  -> SOURCE_READY
  -> SOURCE_PROTECTION_FAILURE
  -> BACKUP_FAILED

SOURCE_PROTECTION_FAILURE
  -> SOURCE_DETECTED
  -> IDLE

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

PREFLIGHT_WARNING
  -> BACKUP_QUEUED
  -> PREFLIGHT_BLOCKED

BACKUP_QUEUED
  -> BACKUP_COPYING
  -> BACKUP_CANCELLED

BACKUP_COPYING
  -> BACKUP_VERIFYING
  -> BACKUP_CANCELLING
  -> RECOVERY_REQUIRED
  -> BACKUP_FAILED

BACKUP_VERIFYING
  -> BACKUP_COPYING
  -> BACKUP_COMPLETED
  -> BACKUP_COMPLETED_WITH_WARNINGS
  -> BACKUP_CANCELLING
  -> RECOVERY_REQUIRED
  -> BACKUP_FAILED

BACKUP_CANCELLING
  -> BACKUP_CANCELLED
  -> RECOVERY_REQUIRED

BACKUP_COMPLETED
  -> SOURCE_SAFE_TO_REMOVE

BACKUP_COMPLETED_WITH_WARNINGS
  -> SOURCE_SAFE_TO_REMOVE

BACKUP_CANCELLED
  -> SOURCE_SAFE_TO_REMOVE
  -> PREFLIGHT_SCANNING

RECOVERY_REQUIRED
  -> RECOVERING

RECOVERING
  -> PREFLIGHT_SCANNING
  -> BACKUP_COPYING
  -> BACKUP_VERIFYING
  -> BACKUP_COMPLETED
  -> BACKUP_FAILED

SOURCE_SAFE_TO_REMOVE
  -> IDLE
```

Every transition shall:

1. Validate the transition.
2. Persist the new state in the appropriate authoritative database.
3. Create an event record.
4. Publish a state event to subscribers.
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

The mount layer shall:

1. Detect whether the volume is already mounted.
2. Reject an unexpected writable mount.
3. Request block-device read-only mode using the Linux block-device interface.
4. Confirm block-device read-only state where exposed.
5. Mount the source with read-only options.
6. Inspect `/proc/self/mountinfo` or equivalent authoritative mount information.
7. Confirm effective filesystem read-only status.
8. Only then transition to `MOUNTED_READ_ONLY`.

The backup engine shall never trust requested mount options without verifying effective state.

Automatic filesystem repair shall be disabled.

Version 1 source filesystem drivers shall be limited to:

```text
vfat
exfat
```
# 10. Destination Mounting and Validation

The destination SSD shall be configured by filesystem UUID.

At service startup and before each preflight:

1. Find the configured UUID.
2. Confirm exactly one matching volume.
3. Confirm filesystem type is `ext4`.
4. Confirm writable mount state.
5. Confirm backup root exists or can be created.
6. Confirm `.aethereal` metadata root exists or can be created.
7. Confirm canonical object store exists or can be created.
8. Open the destination manifest.
9. Validate manifest schema compatibility.
10. Confirm free capacity.
11. Record destination device metadata.

If validation fails, backup shall remain blocked.

The implementation shall not silently downgrade to exFAT or another filesystem.
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

# 12. Content Identity and Source Snapshot Strategy

The definitive content identity is:

```text
size_bytes + SHA-256
```

Version 1 uses strict source hashing.

For every regular file during fresh preflight:

1. Open the source file read-only.
2. Read it in streaming chunks on the bounded I/O worker pool.
3. Calculate SHA-256.
4. Persist the resulting content identity with the preflight.

Do not reuse a historical hash based only on:

```text
source volume
relative path
size
mtime
```

Hash files in streaming chunks.

Suggested initial chunk size:

```text
8 MiB
```

After every regular source file has a fresh content hash, build a canonical manifest sorted by normalized relative path.

Each manifest record shall encode:

```text
relative_path
size_bytes
sha256
```

Calculate:

```text
source_snapshot_sha256 = SHA256(canonical_manifest_bytes)
```

The source snapshot hash is used for interrupted-job source matching.

Observed FAT or exFAT volume serials remain metadata, not proof that the same snapshot is present.
# 13. Preflight Implementation

The strict preflight pipeline shall be:

```text
VALIDATE TRUSTED CLOCK
      |
      v
VALIDATE SOURCE
      |
      v
VALIDATE DESTINATION + EXT4
      |
      v
INVENTORY SOURCE
      |
      v
FRESH SHA-256 OF EVERY REGULAR SOURCE FILE
      |
      v
CALCULATE SOURCE SNAPSHOT IDENTITY
      |
      v
COMPARE WITH VERIFIED CANONICAL OBJECT STORE
      |
      v
PLAN SESSION HARDLINKS
      |
      v
DETECT SESSION PATH CONFLICTS
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
    new_content_object_bytes
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
+
estimated_manifest_and_session_metadata
```

This formula shall be validated during implementation and documented as the v1 rule.

A dry run executes the same pipeline but does not transition into copying.
# 14. Backup Planning

The planner shall generate an immutable file and session plan for the job.

Each source file plan shall contain:

```text
source_file_id
content_identity_id
source_path
canonical_object_final_path
canonical_object_partial_path
session_final_path
planned_size_bytes
classification
action
```

Action shall be one of:

```text
COPY_VERIFY_OBJECT_AND_LINK
LINK_EXISTING_VERIFIED_OBJECT
BLOCK_CONFLICT
```

For `NEW` content:

- Plan a canonical object copy.
- Plan three-way hash verification.
- Plan a session hardlink.

For `ALREADY_BACKED_UP` content:

- Do not physically copy content.
- Plan a hardlink from the canonical object into the current session.

`POTENTIAL_CONFLICT` shall block the job.

An unreadable regular source file shall block the job in v1.

The immutable plan shall reference the fresh source snapshot identity.
# 15. Copy and Canonical Object Implementation

For every planned new content object:

1. Create the canonical object parent directory.
2. Confirm the final object path does not exist unexpectedly.
3. Open the source read-only.
4. Open the partial object with exclusive creation.
5. Read source data in chunks on the I/O worker.
6. Calculate the copy-stream SHA-256 while reading.
7. Write the same bytes to the partial object.
8. Update copied-byte progress through the thread-safe event boundary.
9. Flush Python buffers.
10. Call `os.fsync()` on the partial object.
11. Close the destination write descriptor.
12. Compare the copy-stream hash with the strict preflight source hash.
13. Request `POSIX_FADV_DONTNEED` for the synchronized destination range where supported.
14. Reopen the partial object for independent destination hashing.
15. Calculate destination SHA-256.
16. Compare all three hashes.
17. Persist `PENDING_FINALIZE` with expected hash and all relevant paths using a durable destination-manifest transaction.
18. Rename the partial object to the canonical final object path.
19. `fsync()` the canonical object parent directory.
20. Create the planned hardlink into the session path.
21. `fsync()` the session parent directory.
22. Commit canonical object and session entry as `VERIFIED`.

Use:

```text
<sha256>.aethereal-partial
```

for temporary objects.

Do not globally drop Linux caches.

Do not use `shutil.copy2()` as the entire copy abstraction.

Optional direct-I/O destination verification may be implemented behind a capability-tested configuration flag.
# 16. Verification Implementation

Verification is mandatory.

The v1 three-way evidence model is:

```text
H1 = strict preflight source SHA-256
H2 = SHA-256 of source bytes read during copy
H3 = SHA-256 of independently reopened destination object
```

Required condition:

```text
H1 == H2 == H3
```

`H1` comes from the immediately preceding fresh preflight.

`H2` is calculated from the source read stream that is actually written to the destination.

`H3` is calculated only after:

- destination file synchronization,
- close of the write descriptor,
- best-effort per-file cache eviction request,
- reopen of the destination object.

This deliberately performs two source reads for new content:

1. Strict preflight hash read.
2. Copy-stream read.

It also performs one destination write and one destination read.

The strict v1 workload is therefore approximately four content-size units of I/O for new content.

On mismatch:

1. Persist diagnostic hashes.
2. Do not publish a verified canonical object.
3. Remove or quarantine the invalid partial object according to policy.
4. Retry.

Default retries:

```text
2 additional copy attempts
```

Maximum total attempts:

```text
3
```

After final failure:

```text
file state = FAILED
job cannot become BACKUP_COMPLETED
```
# 17. Recovery Implementation

At `backupd` startup:

1. Open the appliance-local database.
2. Validate local schema.
3. Detect and validate the configured destination.
4. Open the destination manifest.
5. Run appropriate manifest integrity checks.
6. Find non-terminal backup jobs.
7. Inspect associated canonical content objects and session paths.
8. Enumerate partial objects.
9. Reconcile `PENDING_FINALIZE` operations.
10. Mark unresolved jobs `RECOVERY_REQUIRED`.
11. Wait for the required source snapshot and destination validation.
12. Run recovery preflight.
13. Resume at file level.

Recovery rules:

- Valid verified canonical objects remain complete.
- Session hardlinks to verified objects remain complete.
- Partial objects are not valid backups.
- A `PENDING_FINALIZE` record contains the expected content identity and intended paths.
- If the final canonical object exists after a crash, rehash it and compare it with the pending expected hash.
- If it matches, complete directory synchronization, session link creation, and final manifest commit.
- If only the partial object exists, rehash and either complete finalization or recopy.
- If neither candidate can be proven, schedule a recopy.
- A different source snapshot shall not be substituted for the original source.

Loss of the appliance-local database shall not destroy authoritative destination verification state.

The destination manifest travels with and describes its SSD.
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
GET  /api/v1/time

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

POST /api/v1/time/sync
POST /api/v1/system/reboot
POST /api/v1/system/shutdown

GET  /api/v1/system
GET  /api/v1/update
POST /api/v1/update
```

WebSocket:

```text
GET /api/v1/events
```

Client startup and reconnect sequence:

```text
authenticate
GET /api/v1/status
connect WebSocket
apply events newer than snapshot sequence
```

The REST API is authoritative for current snapshots.

The WebSocket provides server-pushed deltas and progress events.

Event records shall include monotonically increasing sequence identifiers so reconnect logic can identify gaps.
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

# 22. Authentication and Credential Provisioning

For v1, implement local single-user authentication.

Recommended approach:

- One local administrator account.
- Password hash stored using a modern password-hashing algorithm.
- Secure session cookie.
- CSRF protection for state-changing browser requests.
- Session timeout.
- Re-authentication may be required for shutdown, reboot, or software update.

Provisioning rules:

- The installer prompts for an AP password and web administrator password in interactive mode.
- When a password is omitted, the installer generates a random per-device secret.
- Generated secrets are printed once before final reboot.
- A root-readable provisioning record may retain generated bootstrap secrets until first successful administration or rotation.
- Secrets are not written to the destination backup hierarchy.
- Non-interactive mode consumes secrets through a protected environment or configuration file, not command-line arguments.

The application shall bind only to configured appliance addresses or interfaces.

The installer and verification plan shall test bind scope explicitly.
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

# 24. Power, Thermal, Clock, and System Monitoring

`aethereal-watch` shall poll:

```text
CPU temperature
system storage free capacity
load
memory
undervoltage telemetry when available
clock trust state
RTC availability
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

Clock policy:

- Read qualified RTC during boot when configured.
- Mark clock trusted when RTC, authenticated phone sync, or network time succeeds.
- Refuse creation of dated session folders while clock is untrusted.
- Expose clock source and skew in the web API.
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

Configure the Raspberry Pi as a standalone access point using the networking stack supported by the selected Raspberry Pi OS release.

For current NetworkManager-based Raspberry Pi OS, provisioning shall use `nmcli` and persistent NetworkManager connection profiles.

Implementation tasks:

1. Configure SSID.
2. Configure WPA authentication.
3. Configure static appliance IP.
4. Configure client address assignment.
5. Configure local hostname resolution.
6. Confirm the web application is reachable without internet.
7. Confirm VNC works over the access-point network.
8. Confirm the web service is not unintentionally bound to unrelated interfaces.

The AP configuration shall be staged.

The installer shall not activate a network change that disconnects the provisioning shell before credentials and the final connection summary have been displayed.

Normal AP mode shall start automatically during boot.
# 28. Installation, Provisioning, and Update Delivery

The repository shall publish a versioned `install.sh` in every production GitHub Release.

Documented bootstrap command:

```text
curl -fsSL <release-install.sh-url> -o /tmp/aethereal-install.sh \
  && sudo bash /tmp/aethereal-install.sh
```

The bootstrap installer shall install from a GitHub Release, not from an unpinned `main` checkout.

Installer phases:

```text
PRECHECK
DOWNLOAD
VERIFY_RELEASE
STAGE
CONFIGURE
MIGRATE
INSTALL_SERVICES
HEALTH_CHECK
ACTIVATE_APPLIANCE_MODE
COMPLETE
```

The installer shall:

1. Validate Raspberry Pi hardware and supported Raspberry Pi OS.
2. Validate ARM architecture.
3. Install system dependencies.
4. Download the selected versioned release bundle.
5. Verify `SHA256SUMS`.
6. Verify GitHub build provenance when supported verification tooling is available.
7. Create service users and directories.
8. Create the Python virtual environment.
9. Install the application wheel.
10. Create or migrate the appliance-local database.
11. Prompt for or generate AP and web credentials.
12. Configure the NetworkManager access-point profile.
13. Configure hostname and local name resolution.
14. Enable and validate VNC through the supported Raspberry Pi OS mechanism.
15. Configure the RTC profile and clock trust service.
16. Detect candidate destination volumes.
17. Require explicit destination selection.
18. Validate destination UUID and ext4 filesystem.
19. Initialize or migrate the destination manifest.
20. Install systemd units.
21. Configure log rotation.
22. Write validated configuration.
23. Start services before AP activation where possible.
24. Run local HTTP and backup-service health checks.
25. Print SSID, hostname, fallback IP, and credential outcome.
26. Activate appliance boot mode.
27. Reboot when required.

Installer modes:

```text
interactive
--non-interactive
--repair
--upgrade
--version <semantic-version>
```

Idempotency rules:

- Never format a disk.
- Never replace the configured destination silently.
- Never delete backups or destination manifests.
- Never reset credentials unless explicitly requested.
- Re-running the same version converges configuration and services.
- Interrupted installation state is recorded and `--repair` resumes or repairs staging.

Upgrade implementation:

1. Refuse upgrade while a backup job is active.
2. Download selected release.
3. Verify checksums and provenance.
4. Save current application version and local configuration backup.
5. Run migration preflight.
6. Install the new application into a versioned release directory.
7. Apply migrations.
8. Switch the active release symlink.
9. Restart services.
10. Run health checks.
11. Roll back the active release symlink on health failure when migrations remain reversible.

Suggested layout:

```text
/opt/aethereal-backup/releases/<version>/
/opt/aethereal-backup/current -> releases/<version>
```
# 29. GitHub CI/CD Design

Use GitHub Actions for software CI, installer validation, hardware smoke verification, and release publication.

## Workflow: `ci.yml`

Triggers:

```text
pull_request
push to primary branch
```

Jobs:

```text
lint
type-check
unit-test
integration-test
migration-test
package-build
```

Recommended checks:

```text
ruff format --check
ruff check
mypy or pyright
pytest tests/unit
pytest tests/integration
fresh-db migration test
upgrade-from-supported-schema migration test
python -m build
twine check dist/*
```

Use GitHub-hosted Linux runners for non-hardware tests.

Cache Python package dependencies through the supported Python setup action.

## Workflow: `installer.yml`

Triggers:

```text
pull_request when scripts/** changes
push to primary branch
```

Jobs:

```text
shellcheck
bats installer tests
idempotency fixture
interrupted-stage repair fixture
release-bundle fixture install
```

The installer test harness shall use disposable Linux environments for logic that does not require Raspberry Pi hardware.

## Workflow: `hardware.yml`

Triggers:

```text
workflow_dispatch
nightly schedule
release-candidate gate
```

Runner:

```text
[self-hosted, linux, ARM64, rpi4, aethereal-hw]
```

Hardware smoke tests:

- Detect qualified USB reader.
- Detect qualified destination SSD.
- Enforce source block-device and mount read-only state.
- Validate ext4 destination.
- Execute a small strict preflight.
- Copy, three-way verify, finalize, and create session hardlink.
- Exercise LED.
- Read thermal and undervoltage telemetry.
- Validate VNC and web service health where practical.

Hard power-cut tests remain lab-controlled and shall not run unattended on every PR.

## Workflow: `release.yml`

Trigger:

```text
approved semantic version tag v*
```

Required gates:

```text
software CI passed
installer CI passed
hardware release gate passed
```

Release steps:

1. Build wheel and source distribution.
2. Build versioned appliance release bundle.
3. Include `install.sh`.
4. Generate release metadata with application and schema versions.
5. Generate `SHA256SUMS`.
6. Generate build provenance attestations.
7. Upload workflow artifacts for evidence.
8. Create or update the GitHub Release.
9. Publish release assets.

Production release assets shall be versioned and immutable after approval.

For field units, CD means release publication, not unsolicited remote deployment.

A development staging Pi may be updated automatically from a protected workflow for release-candidate testing.

# 30. Implementation Phases

## Phase 0 - Hardware Qualification

Deliverables:

- Raspberry Pi 4 baseline.
- Qualified high-endurance system storage.
- Qualified power source.
- Qualified ext4 SSD.
- Qualified USB SD reader.
- Cooling configuration.
- External RTC decision and qualified profile.
- LED hardware decision.
- Qualified Raspberry Pi GitHub Actions self-hosted runner.

Exit criteria:

- SSD and SD reader operate simultaneously under the strict four-I/O-unit workload.
- No persistent undervoltage.
- Sustained hashing workload remains thermally acceptable.
- RTC and clock-trust behavior is validated.
- Hardware runner can execute the `hardware.yml` smoke workflow.
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

## Phase 3 - Inventory, Identity, Snapshot, and Preflight

Implement:

- Source inventory.
- Fresh SHA-256 of every regular source file.
- Content identity.
- Canonical source snapshot identity.
- Duplicate detection against canonical content objects.
- Complete-session hardlink planning.
- Conflict detection.
- Capacity planning.
- Dry run.

Exit criteria:

- Dry run classifies new and already-backed-up content correctly.
- Insufficient space blocks backup.
- Same filename with different content is detected.
- Same size and mtime with different content is detected.
- Two cards with colliding observed volume metadata are not conflated when snapshot hashes differ.
## Phase 4 - Copy, Object Store, and Verification Engine

Implement:

- Immutable backup plan.
- Canonical content object store.
- Partial-object copy.
- Copy-stream hashing.
- Durable file flush.
- Per-file destination cache-eviction request.
- Independent reopened destination hashing.
- Three-way SHA-256 comparison.
- Durable `PENDING_FINALIZE`.
- Atomic canonical object rename.
- Directory synchronization.
- Session hardlink creation.
- Retry policy.
- Progress tracking.

Exit criteria:

- Every completed destination object has H1 == H2 == H3.
- Partial objects are never marked valid.
- Hash mismatch prevents job completion.
- A completed session presents a complete snapshot view.
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

## Phase 8 - Appliance Provisioning and GitHub Delivery

Implement:

- NetworkManager Wi-Fi access point.
- VNC.
- RTC and phone-time synchronization.
- systemd services.
- Idempotent release installer.
- Repair mode.
- Versioned release directories and active symlink.
- Upgrade and rollback process.
- GitHub Actions software CI.
- Installer CI.
- Raspberry Pi hardware workflow.
- Release workflow with checksums and provenance.

Exit criteria:

- Fresh Raspberry Pi can be provisioned from a versioned GitHub Release through the documented bootstrap command.
- Installer can be rerun without changing destination or deleting state.
- Interrupted installation can be repaired.
- Appliance boots into READY without manual shell interaction when clock and media prerequisites are satisfied.
- Tagged release produces complete installable assets.
## Phase 9 - Verification and Field Qualification

Execute the Verification Plan.

Exit criteria:

- All v1 acceptance criteria pass.
- No open critical or high-severity integrity defects.
- Field workflow validated with Canon and DJI media.

---

# 31. Definition of Done

Implementation is complete only when:

- The software is installable from a versioned GitHub Release through the documented bootstrap command.
- The installer configures AP networking, VNC, credentials, RTC/time support, services, storage identity, and persistent state.
- The installer is idempotent.
- Interrupted installation can be repaired.
- Release checksum verification is mandatory.
- Release provenance verification is implemented when supported tooling is available.
- All database migrations are explicit, versioned, and tested.
- The destination manifest uses WAL mode and synchronous FULL.
- The full PRD requirement set is traceable to implementation components.
- Automated unit and integration tests pass.
- Installer CI passes.
- Raspberry Pi hardware smoke verification passes.
- The Verification Plan exit criteria are satisfied.
- The target hardware configuration is qualified.
- A clean appliance can execute the complete field workflow without shell access.
- A semantic-version release produces wheel, source distribution, appliance bundle, installer, checksums, release metadata, and provenance evidence.
