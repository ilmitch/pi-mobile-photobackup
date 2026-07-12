# Aethereal Mobile Backup Appliance

## Product Requirements Document

**Version:** 0.3  
**Product status:** v1 implementation baseline  
**Primary platform:** Raspberry Pi 4  
**Primary use case:** Field backup of photography and drone media without requiring internet access

---

# 1. Product Summary

Aethereal Mobile Backup is a portable, screenless backup appliance designed for photographers operating in the field.

The device automatically detects removable source media, performs a read-only source scan, determines which content requires backup, verifies destination capacity, copies new content to an external SSD, cryptographically verifies copied files, and provides physical and web-based status reporting.

The primary target sources are:

- Canon EOS R6 Mark II memory cards
- DJI Mini 5 Pro memory cards

The architecture shall remain camera-agnostic and shall support generic removable media containing regular files.

The device shall operate without internet access.

Normal operation shall not require a monitor, keyboard, mouse, SSH session, or VNC connection.

---

# 2. Product Goals

The product shall:

- Protect original source media from modification.
- Detect newly inserted source media.
- Determine which files require backup using strict content hashing.
- Prevent a backup from starting when destination capacity is insufficient.
- Copy source content to an external SSD.
- Verify every copied file using independent source, copy-stream, and destination hash evidence.
- Recover safely from interrupted backup operations.
- Avoid physically duplicating content already verified on the destination while presenting each session as a complete snapshot view.
- Provide backup status through a physical LED.
- Provide detailed status and controls through a local mobile web application.
- Operate through its own standalone Wi-Fi network.
- Support administrative access through VNC.
- Operate without internet connectivity after provisioning.
- Maintain persistent backup history and operational logs.
- Support repeatable, idempotent installation from a versioned GitHub release.
- Support automated build, test, release, and hardware-verification workflows through GitHub Actions.
# 3. Non-Goals

Version 1 shall not:

- Delete files from source media.
- Format memory cards.
- Repair damaged source filesystems.
- Synchronise files to cloud storage.
- Edit or catalogue photographs.
- Generate previews or thumbnails.
- Analyse photographic content.
- Determine which photographs are valuable.
- Automatically delete destination files.
- Automatically delete old backup sessions.
- Run concurrent backup jobs.
- Copy from multiple source cards simultaneously.
- Provide RAID protection.
- Guarantee byte-level continuation of a partially copied individual file.
- Guarantee native destination-SSD readability on Windows or macOS.
- Automatically push deployments from GitHub to field appliances that are offline.
- Use source path, file size, or modification time as a v1 shortcut to skip source hashing.

Interrupted jobs shall resume at file level.

A partially copied file may be recopied from the beginning.

The v1 destination filesystem correctness profile prioritises Linux durability semantics over native cross-platform SSD mounting.
# 4. Hardware Assumptions

The reference hardware configuration consists of:

- Raspberry Pi 4
- Qualified high-endurance Raspberry Pi system storage
- External USB SSD formatted with ext4
- USB SD card reader
- Suitable field power source
- Raspberry Pi Wi-Fi interface
- Controllable status LED
- External RTC module for the qualified reference configuration, recommended DS3231-class hardware

The external SSD shall use a USB 3 host port.

The SD card reader shall use a separate USB host port.

The Raspberry Pi USB-C connector used for device power shall not be treated as a removable-media host connection.

The system shall be validated with the intended SSD, SD card reader, enclosure, cooling solution, RTC configuration, system storage, and field power source as a complete hardware configuration.

A deployment without an RTC may be supported only when the software can establish trusted wall-clock time through the web client or another configured time source before creating a dated backup session.
# 5. Primary User Workflow

The intended field workflow shall be:

```text
POWER ON DEVICE
        |
        v
SYSTEM READY
        |
        v
INSERT SD CARD
        |
        v
DETECT SOURCE
        |
        v
MOUNT READ-ONLY
        |
        v
PREFLIGHT
        |
        +---- SOURCE ERROR ---------> BLOCKED
        |
        +---- SSD ERROR ------------> BLOCKED
        |
        +---- NO CAPACITY ----------> BLOCKED
        |
        +---- WARNINGS -------------> READY WITH WARNINGS
        |
        v
READY TO BACK UP
        |
        v
COPY
        |
        v
VERIFY
        |
        v
BACKUP COMPLETE
        |
        v
SOURCE SAFE TO REMOVE
```

The user shall be able to perform this workflow without accessing the web interface.

The web interface shall provide additional visibility and control.

---

# 6. System Architecture

The system shall use a central backup engine as the authoritative owner of backup state.

```text
                     SOURCE MEDIA
                           |
                           v
                  +-----------------+
                  |                 |
                  |  BACKUP ENGINE  |
                  |                 |
                  +--------+--------+
                           |
                           v
                    DESTINATION SSD

                           |
                    STATE AND EVENTS
                           |
             +-------------+-------------+
             |             |             |
             v             v             v
          WEB UI          LED          LOGGING
```

The LED controller and web application shall not independently infer backup status from filesystem activity.

The backup engine shall publish authoritative state and progress information.

---

# 7. Core Services

The reference software architecture shall contain:

```text
Raspberry Pi OS with Desktop
        |
        +-- Wi-Fi access point
        |
        +-- backupd
        |      |
        |      +-- media detection
        |      +-- preflight
        |      +-- copy engine
        |      +-- verification
        |      +-- recovery
        |
        +-- SQLite operational database
        |
        +-- Local web application
        |      |
        |      +-- API
        |      +-- real-time status
        |      +-- mobile UI
        |
        +-- LED status controller
        |
        +-- system service manager
```

The backup worker and web application shall run as separate service processes.

A failure of the web application shall not terminate an active backup.

A backup shall continue when the iPhone disconnects from Wi-Fi.

---

# 8. Wi-Fi Access Point Requirements

## NET-001 - Standalone Access Point

The Raspberry Pi shall automatically start a dedicated Wi-Fi access point during system startup.

The appliance shall not require an external router.

The appliance shall not require a mobile hotspot.

The appliance shall not require internet access.

Suggested default SSID:

`Aethereal-Backup`

The Wi-Fi network shall require authentication.

The access point shall provide IP configuration to connected clients.

## NET-002 - Predictable Device Address

The web application shall be reachable through a predictable local hostname.

Suggested hostname:

`backup.local`

The Raspberry Pi shall also use a stable private network address as a fallback.

The fixed IP address shall be documented in the web and device configuration.

## NET-003 - Access Point Availability

The access point shall remain available during:

- Preflight
- Backup
- Verification
- Recovery

A backup shall not stop when a Wi-Fi client disconnects.

---

# 9. Remote Administration

## ADM-001 - VNC Access

The Raspberry Pi shall provide a graphical desktop environment.

VNC shall be available for administrative and recovery operations.

VNC shall be considered a secondary administration interface.

Normal backup operation shall not require VNC.

VNC may be used to:

- Inspect the filesystem
- Review system state
- Perform advanced configuration
- Troubleshoot services
- Perform system maintenance

---

# 10. Source Media Protection

## SRC-001 - Read-Only Source Access

All removable source media shall be treated as read-only.

The system shall not intentionally:

- Create files on source media
- Modify files on source media
- Delete files from source media
- Rename files on source media
- Move files on source media
- Write logs to source media
- Write database files to source media
- Write indexes to source media
- Write thumbnails to source media

Before mounting a source, the appliance shall request block-device read-only mode where the Linux block-device interface supports it.

Source media shall then be mounted read-only before scanning begins.

## SRC-002 - Effective Mount Validation

The backup engine shall verify both:

- The effective block-device read-only state, when available.
- The effective filesystem mount state.

A backup shall only proceed when the source state is:

`MOUNTED_READ_ONLY`

A writable source block device or writable source mount shall cause the operation to enter:

`SOURCE_PROTECTION_FAILURE`

The backup shall be blocked.

The event shall be logged as a critical error.

## SRC-003 - Source State Model

Source media states shall include:

```text
NOT_PRESENT
DETECTED
MOUNTING_READ_ONLY
MOUNTED_READ_ONLY
MOUNT_FAILED
UNSUPPORTED_FILESYSTEM
SOURCE_PROTECTION_FAILURE
REMOVED
```

## SRC-004 - Filesystem Repair

The appliance shall not automatically repair a source filesystem.

The appliance shall not automatically run filesystem repair or optimisation operations against source media.

When filesystem corruption or inconsistency prevents reliable reading, the source shall be rejected.

The web interface shall report that separate recovery or inspection is required.
# 11. Source Media Identity

## SRC-005 - Observed Source Volume Identity

The system shall collect available source identity information.

Observed identity attributes shall include, when available:

- Filesystem serial or UUID
- Volume label
- Filesystem type
- Total capacity
- Partition start and partition size
- Device identifier
- Device model
- Device serial identifier

The physical mount path shall not be considered a stable source identity.

Observed volume identity shall not be sufficient to prove content identity or to authorise interrupted-job recovery.

## SRC-006 - User Source Name

The web interface shall allow a user-defined logical source name.

Examples:

```text
CANON_CARD_01
CANON_CARD_02
DJI_CARD_01
```

The logical name shall not replace technical media identity.

It shall be stored as metadata associated with the observed volume.

## SRC-007 - Source Snapshot Identity

Every completed strict preflight shall calculate a deterministic source snapshot identity.

The source snapshot identity shall be derived from a canonical ordered manifest containing, for every regular source file:

- Relative source path
- File size
- SHA-256 content hash

The canonical manifest shall be sorted by normalized relative path.

The snapshot identity shall be the SHA-256 hash of the canonical manifest representation.

Interrupted-job recovery shall require the source snapshot identity expected by the job.

A different card with a colliding filesystem serial or label shall not be accepted as the interrupted job source when its snapshot identity differs.
# 12. Supported Source Content

## FILE-001 - File Selection Policy

The default backup policy shall copy every regular file contained within configured source roots.

The appliance shall not limit backup to known photographic extensions.

The appliance shall not determine whether a file is valuable.

Canon-specific or DJI-specific file extensions may be displayed as metadata but shall not control the default backup policy.

Directories and filesystem metadata required solely by the source filesystem do not need to be copied as independent content.

Symbolic links and special filesystem objects shall not be followed unless explicitly supported by a future version.

## FILE-001A - Supported Source Filesystems

Version 1 shall explicitly support source media using:

- FAT32, exposed by Linux as `vfat`
- exFAT, exposed by Linux as `exfat`

Additional source filesystems shall be treated as unsupported until qualification and verification evidence exists.

The source filesystem type shall be shown in the web interface and recorded in backup history.
# 13. File Identity and Duplicate Detection

## FILE-002 - Definitive Content Identity

The definitive content identity of a file shall be based on:

```text
FILE SIZE
+
SHA-256 CONTENT HASH
```

Filename shall not prove content identity.

Relative path shall not prove content identity.

Modification timestamp shall not prove content identity.

Camera metadata shall not prove content identity.

## FILE-003 - Source File Instance Identity

A source file instance shall be described by:

- Source volume identity
- Relative source path
- File size
- Modification timestamp, when available

This information may be used to identify a previously observed source file instance.

## FILE-004 - Strict Source Hashing

Version 1 shall use strict source hashing by default.

Every regular source file shall be SHA-256 hashed during the fresh preflight that immediately precedes a backup.

The appliance shall not skip source hashing based only on:

- Observed source volume identity
- Relative source path
- File size
- Modification timestamp

A file hash recorded during an earlier backup may be displayed as historical metadata but shall not replace the fresh v1 preflight hash.

A future performance mode may introduce a hash cache only as an explicitly less-conservative operating profile with separate requirements and verification.
## FILE-005 - Already Backed Up Definition

A file shall be classified as:

`ALREADY_BACKED_UP`

only when its definitive content identity matches a destination object previously marked:

`VERIFIED`

The destination manifest shall identify the verified content object.

The canonical destination object shall exist and shall remain associated with the expected content identity.

A manifest record without a corresponding valid destination object shall not be sufficient.

When content is already backed up, the current backup session shall still receive a session entry for the source-relative path through a hardlink to the verified canonical content object.
## FILE-006 - File Classification

Preflight shall classify source files as:

```text
NEW
ALREADY_BACKED_UP
POTENTIAL_CONFLICT
UNSUPPORTED
UNREADABLE
```

A file with the same filename but different content identity shall not be classified as already backed up.

## FILE-007 - Filename Collision Protection

An existing destination file shall never be silently overwritten.

When a destination path is already occupied by content with a different content identity, the state shall become:

`POTENTIAL_CONFLICT`

The conflict shall be visible in the dry-run and preflight result.

The system shall preserve both contents or block the operation according to the configured conflict policy.

The default v1 policy shall be:

`BLOCK CONFLICTING DESTINATION PATH`

No overwrite confirmation option shall be provided during automatic backup.

---

# 14. Destination SSD Requirements

## DST-001 - Explicit Destination Identity

The backup destination shall be explicitly configured.

The destination SSD shall be identified primarily through filesystem UUID.

An arbitrary newly connected USB storage device shall not automatically become the backup destination.

## DST-002 - Destination Validation

Before preflight, the system shall verify:

- Destination device presence
- Expected destination identity
- Destination filesystem type
- Destination mount state
- Destination write access
- Backup root accessibility
- Available filesystem capacity

A failed destination validation shall block backup.

## DST-003 - Multiple Destination Devices

When multiple writable USB storage devices are detected, the configured destination identity shall remain authoritative.

The system shall not select a destination based solely on connection order or mount path.

## DST-004 - Destination Filesystem

The version 1 correctness profile shall require the destination SSD to use ext4.

A non-ext4 destination shall enter:

`UNSUPPORTED_DESTINATION_FILESYSTEM`

and shall block backup.

The appliance shall rely on Linux file and directory synchronisation semantics during finalization and recovery.

Native Windows or macOS mounting of the destination SSD is not a version 1 requirement.

## DST-005 - Canonical Content Store

The destination shall contain an appliance-managed canonical content store.

The default content store root shall be:

```text
/Backups/.aethereal/objects/sha256/
```

Canonical content objects shall be addressed by SHA-256 identity.

Example:

```text
/Backups/.aethereal/objects/sha256/ab/cd/<sha256>
```

The canonical content store shall not be presented as the normal photographer-facing backup hierarchy.
# 15. Destination Folder Structure

## DST-006 - Backup Session Structure

Each backup operation shall use a dedicated backup session directory.

The default structure shall be:

```text
/Backups/
    /YYYY/
        /YYYY-MM-DD/
            /<BACKUP_JOB_ID>_<SOURCE_NAME>/
                <SOURCE_RELATIVE_PATH>
```

Example:

```text
/Backups/
    /2026/
        /2026-07-11/
            /20260711-001_CANON_CARD_01/
                /DCIM/
                    /100CANON/
                        IMG_8421.CR3
                        IMG_8422.CR3
```

## DST-007 - Complete Snapshot View

A completed backup session shall present a complete snapshot view of every regular file included in the source snapshot.

The session directory shall not contain only files that were new during that job.

For new content:

- The content shall be copied and verified into the canonical content store.
- A hardlink shall then be created at the source-relative path inside the session directory.

For already verified content:

- A hardlink shall be created from the verified canonical content object into the current session directory.

The complete source-relative directory structure shall be preserved.

Deleting an older session directory shall not invalidate the content visible through a later completed session, because the canonical object and later hardlinks shall retain independent link references to the same inode.

A session is a complete snapshot view, not a promise that every session physically duplicates every byte.

## DST-008 - Session Metadata Semantics

Hardlinked session entries share inode metadata with their canonical content object.

Version 1 guarantees byte-for-byte file content and path preservation.

Version 1 does not guarantee preservation of every source filesystem inode timestamp or permission bit in the session file inode.

Source-observed timestamps and source metadata shall be retained in the operational manifest.

## DST-009 - Session Naming

Every backup job shall receive a unique backup job ID.

The job ID shall be stable and stored in the destination manifest.

The folder name shall include:

- Trusted backup date
- Backup sequence or unique job identifier
- Sanitised logical source name
# 16. Mandatory Backup Preflight

## PRE-001 - Preflight Requirement

Every backup operation shall perform a fresh preflight before copying content.

This requirement applies to:

- Automatic backup
- Manually initiated backup
- Retried backup
- Resumed interrupted backup where media state has changed

No file content shall be copied during preflight.

## PRE-002 - Preflight States

The backup state machine shall include:

```text
PREFLIGHT_SCANNING
PREFLIGHT_HASHING
PREFLIGHT_COMPARING
PREFLIGHT_CAPACITY_CHECK
PREFLIGHT_READY
PREFLIGHT_WARNING
PREFLIGHT_BLOCKED
```

## PRE-003 - Source Inventory and Strict Hashing

Preflight shall construct an inventory of candidate source files.

For every file, the system shall collect:

- Relative path
- Filename
- File size
- Modification timestamp, when available
- Observed source volume identity
- Fresh SHA-256 content hash

The system shall SHA-256 hash every regular source file during the fresh preflight.

After hashing completes, the system shall calculate the deterministic source snapshot identity.

The source snapshot identity and per-file content identities shall be persisted as part of the preflight evidence.
## PRE-004 - Capacity Calculation

Preflight shall calculate:

- Destination total capacity
- Destination currently available capacity
- Number of new files
- Total bytes of new files
- Operational reserve
- Safety margin
- Required destination capacity
- Estimated destination capacity after backup

Required space shall be calculated as:

```text
NEW_FILE_BYTES
+
OPERATIONAL_RESERVE
+
SAFETY_MARGIN
```

## PRE-005 - Destination Safety Margin

The default safety margin shall be the greater of:

```text
5 percent of destination filesystem capacity
```

or:

```text
10 GB
```

The safety margin shall be configurable.

## PRE-006 - Operational Reserve

The capacity calculation shall include deterministic operational reserve.

The reserve shall account for:

- The largest new content object being copied
- Temporary destination object files
- Destination-manifest growth
- Application logs and system operational state
- Session directory and hardlink metadata
- Verification-related filesystem operations

The reserve calculation shall be documented.

The v1 implementation shall not rely on the assumption that aggregate source file bytes alone are sufficient destination capacity.
## PRE-007 - Insufficient Capacity

When available destination capacity is lower than calculated required capacity, the backup shall enter:

`PREFLIGHT_BLOCKED`

The backup shall not start.

The user interface shall display:

- Available capacity
- New content size
- Operational reserve
- Safety margin
- Required capacity
- Capacity shortfall

Example:

```text
New content:          177.1 GB
Operational reserve:   0.3 GB
Safety margin:         10.0 GB
Required capacity:    187.4 GB
Available capacity:   169.8 GB

Shortfall:             17.6 GB

BACKUP BLOCKED
```

## PRE-008 - No Capacity Override

Version 1 shall not provide a force-backup option when destination capacity is insufficient.

The user shall not be able to override:

`PREFLIGHT_BLOCKED`

for insufficient destination capacity.

---

# 17. Manual Dry Run

## DRY-001 - Dry-Run Operation

The web application shall provide a `Dry Run` action.

A dry run shall perform the complete backup planning and preflight process without copying file content.

## DRY-002 - Dry-Run Result

The dry-run result shall include:

- Source identity
- Logical source name
- Number of files discovered
- Number of new files
- Number of previously backed-up files
- Number of potential conflicts
- Number of unreadable files
- Total source bytes scanned
- New bytes requiring backup
- Destination free capacity
- Operational reserve
- Safety margin
- Required backup capacity
- Estimated destination capacity after backup
- Proposed backup session directory

## DRY-003 - Dry-Run Outcome

A dry run shall terminate with one of:

```text
READY_TO_BACKUP
READY_WITH_WARNINGS
BACKUP_BLOCKED
```

A dry run shall never automatically transition into a copy operation.

## DRY-004 - Fresh Preflight

A previous dry run shall not replace the mandatory preflight immediately preceding a backup.

When the user later starts a backup, the system shall revalidate:

- Source presence
- Source identity
- Source read-only state
- Source inventory
- Destination identity
- Destination mount state
- Destination free capacity

---

# 18. Backup Copy Process

## COPY-001 - Temporary Canonical Content Object

New file content shall initially be copied to a temporary object in the canonical content store.

Example:

```text
/Backups/.aethereal/objects/sha256/ab/cd/<sha256>.aethereal-partial
```

A partial object shall not be presented as a valid completed backup.

## COPY-002 - Existing File Protection

The backup engine shall not overwrite an existing verified canonical content object.

Destination session path collisions shall be resolved before content copying or hardlink finalization begins.

## COPY-003 - Copy State

File copy states shall include:

```text
PLANNED
COPYING
COPIED_PENDING_VERIFICATION
VERIFYING
PENDING_FINALIZE
VERIFIED
FAILED
```

## COPY-004 - Copy-Stream Hash

While reading source bytes for the copy operation, the backup engine shall independently calculate a copy-stream SHA-256 hash.

The copy-stream hash shall match the fresh source SHA-256 calculated during preflight.

A mismatch shall be treated as an unstable or inconsistent source read.

The destination shall not be finalized.

## COPY-005 - Durable File Write

After the temporary object copy completes, the backup engine shall:

1. Flush application buffers.
2. Call file synchronization on the temporary object.
3. Close the write descriptor.
4. Request per-file cache eviction for the synchronized destination range where supported.
5. Reopen the temporary object for independent destination verification.

The application shall not treat a completed userspace write operation alone as proof of a durable backup.

Global operating-system cache dropping shall not be required by the application.
# 19. File Verification

## VER-001 - Mandatory Verification

Every newly copied content object shall be cryptographically verified.

Verification shall not be optional in version 1.

## VER-002 - Verification Algorithm

SHA-256 shall be used as the default content verification algorithm.

For a new content object, the following values shall match:

- Fresh preflight source SHA-256
- Copy-stream SHA-256
- Independently re-read destination SHA-256

## VER-003 - Verification Workflow

The required workflow shall be:

```text
STRICT PREFLIGHT SOURCE HASH
        |
        v
COPY TO TEMPORARY OBJECT
+ HASH COPY STREAM
        |
        v
COPY-STREAM HASH == PREFLIGHT HASH?
        |
       YES
        |
        v
FSYNC TEMPORARY OBJECT
        |
        v
REQUEST PER-FILE CACHE EVICTION
        |
        v
CLOSE + REOPEN DESTINATION
        |
        v
INDEPENDENT DESTINATION SHA-256
        |
        v
ALL THREE HASHES MATCH?
      /     \
    YES      NO
     |        |
     v        v
 PERSIST     ERROR
 PENDING
 FINALIZE
```

Use of direct I/O for destination verification may be provided as an optional strict or qualification mode when supported by the selected filesystem and implementation.

Direct I/O shall not replace file and directory synchronization requirements.

## VER-004 - Crash-Recoverable Finalization

After successful three-way hash verification:

1. The engine shall persist the expected content identity, temporary object path, final object path, and intended session path in a `PENDING_FINALIZE` manifest state.
2. The `PENDING_FINALIZE` transaction shall be durably committed.
3. The temporary object shall be atomically renamed to its final canonical object path.
4. The canonical object parent directory shall be synchronized.
5. The session hardlink shall be created at the final source-relative session path.
6. The session parent directory shall be synchronized.
7. The destination manifest shall transactionally mark the content object and session entry `VERIFIED`.

The destination file shall only be considered a successful backup after these operations complete.

## VER-005 - Verification Failure

When any required hash does not match:

- The canonical final object shall not be published as verified.
- The session final path shall not be created as a verified entry.
- The event shall be logged.
- The backup job shall enter a warning or failed state according to retry policy.

The system shall retry the copy a configurable number of times.

The default retry count shall be:

`2`

After retries are exhausted, the file state shall become:

`FAILED`

The backup result shall not be:

`COMPLETED`
# 20. Backup Job States

The central backup state model shall support:

```text
IDLE

SOURCE_DETECTED
SOURCE_MOUNTING
SOURCE_READY

PREFLIGHT_SCANNING
PREFLIGHT_HASHING
PREFLIGHT_COMPARING
PREFLIGHT_CAPACITY_CHECK
PREFLIGHT_READY
PREFLIGHT_WARNING
PREFLIGHT_BLOCKED

BACKUP_QUEUED
BACKUP_COPYING
BACKUP_CANCELLING

BACKUP_VERIFYING

BACKUP_COMPLETED
BACKUP_COMPLETED_WITH_WARNINGS
BACKUP_CANCELLED
BACKUP_FAILED

SOURCE_SAFE_TO_REMOVE

RECOVERY_REQUIRED
RECOVERING
```

The backup engine shall be the sole authority for these states.

---

# 21. Interrupted Backup Recovery

## REC-001 - Interrupted Job Detection

During service startup, the backup engine shall detect jobs that did not reach a terminal state.

Examples include jobs left in:

```text
BACKUP_COPYING
BACKUP_VERIFYING
BACKUP_CANCELLING
```

Such jobs shall be treated as interrupted.

## REC-002 - Filesystem and Manifest Reconciliation

Recovery shall inspect both:

- Destination manifest state
- Destination filesystem state

The destination manifest shall not be treated as the sole source of truth regarding file existence.

The destination filesystem shall not be treated as proof that a file was successfully verified.

A `PENDING_FINALIZE` record shall contain sufficient expected content identity and path information to reconcile a power loss before or after rename and before final verified-state commit.
## REC-003 - Partial Files

Files ending in the configured temporary suffix shall be considered incomplete unless explicitly associated with an active valid copy operation.

Version 1 shall use file-level recovery.

An interrupted partial file may be removed and recopied from the beginning.

Byte-level continuation of a partial file is not required.

## REC-004 - Verified and Pending-Finalize Reconciliation

Files previously recorded as `VERIFIED` and confirmed to exist as the expected canonical content object shall not be recopied.

For a `PENDING_FINALIZE` operation, recovery shall:

1. Inspect the temporary and final canonical object paths.
2. Recalculate the hash of any candidate object that exists.
3. Compare the result with the expected content identity already persisted in the pending record.
4. Complete rename, directory synchronization, session hardlink creation, and manifest commit when safe.
5. Otherwise discard the incomplete candidate and schedule the content for recopy.

An interrupted backup shall therefore resume without unnecessarily recopying previously verified or safely reconcilable content.
## REC-005 - Recovery Preflight

Before resuming an interrupted job, the system shall revalidate:

- Source presence
- Source identity
- Source read-only state
- Destination identity
- Destination mount state
- Destination capacity

When the original source is no longer present, the job shall remain incomplete.

The system shall not silently continue using a different source volume.

## REC-006 - Power Loss

Unexpected power loss shall not cause partial files to be classified as valid backups.

After restart, the system shall reconcile the interrupted job before allowing it to transition to a completed state.

## REC-007 - Source Removal During Backup

When source media is removed during backup:

- The active file operation shall fail safely.
- The job shall stop.
- The state shall indicate source removal.
- The event shall be logged.
- Previously verified destination files shall remain valid.

The job may resume after the same source media is reinserted and successfully identified.

## REC-008 - Destination Removal During Backup

When the destination SSD is removed during backup:

- The backup operation shall immediately stop further copy scheduling.
- The current operation shall be treated as interrupted.
- The job shall enter a failed or recovery-required state.
- No partial file shall be considered valid.

A new backup shall not begin until the configured destination SSD is revalidated.

---

# 22. Multiple Source Media

## SRC-007 - Single Active Source

Version 1 shall support one active source volume at a time.

Concurrent backup jobs shall not be supported.

## SRC-008 - Multiple Sources Detected

When multiple valid source media are simultaneously detected, the system shall enter:

`MULTIPLE_SOURCES_DETECTED`

Automatic backup shall not begin.

The web interface shall allow the user to select one source.

Only one source may become active.

---

# 23. Safe Removal

## SAFE-001 - Source Safe to Remove

A source shall only be reported as safe to remove when:

- No source file is open by the backup engine.
- No hashing operation is active.
- No preflight scan is active.
- No copy operation is active.
- No verification read from the source is active.

The system shall then transition to:

`SOURCE_SAFE_TO_REMOVE`

## SAFE-002 - Destination Safe Removal

The web interface shall provide a `Safely Remove SSD` operation.

The operation shall:

1. Reject new backup jobs.
2. Wait for active operations to reach a safe stopping state.
3. Flush application state.
4. Flush SQLite state.
5. Flush destination filesystem operations.
6. Unmount the destination filesystem.
7. Confirm that the destination is safe to remove.

## SAFE-003 - Removal During Active Backup

The web interface shall warn the user before allowing a cancellation associated with media removal.

A cancelled backup shall remain recorded in backup history.

Previously verified files shall remain valid.

---

# 24. Persistent Operational State and Destination Manifest

## DB-001 - Split Persistence Model

Version 1 shall use two SQLite databases with different authority.

The appliance-local database shall store:

- Appliance configuration metadata
- Installation identity
- Source logical aliases
- Non-authoritative system events
- Provisioning and software version metadata

Suggested path:

```text
/var/lib/aethereal-backup/appliance.db
```

The destination SSD shall contain the authoritative backup manifest for content stored on that SSD.

Suggested path:

```text
/Backups/.aethereal/manifest.sqlite3
```

The destination manifest shall store:

- Backup jobs
- Preflight evidence
- Source snapshots
- Per-file source identities
- Canonical content objects
- Session entries
- Copy operations
- Verification results
- Recovery state
- Backup event history

Backup correctness shall not depend on recent destination verification commits surviving only on Raspberry Pi microSD system storage.

## DB-002 - Destination Manifest Durability

The destination manifest shall use SQLite WAL mode with `PRAGMA synchronous=FULL` for the v1 correctness profile.

Verified-state and `PENDING_FINALIZE` transitions shall be durably committed before the engine advances through the corresponding filesystem finalization boundary.

The database shall contain a schema metadata table recording at minimum:

- Schema version
- Application version that last migrated the schema
- Migration timestamp

All schema changes shall use explicit migrations.

## DB-003 - Minimum Destination Data Model

The destination data model shall include concepts equivalent to:

```text
schema_meta
source_volume
source_snapshot
backup_job
preflight
source_file
content_identity
content_object
session_entry
copy_operation
verification_result
event_log
```

## DB-004 - Backup Job Record

A backup job shall store:

- Backup job ID
- Creation timestamp
- Start timestamp
- End timestamp
- Source identity
- Source snapshot identity
- Logical source name
- Destination identity
- Destination session path
- Files discovered
- Files planned
- Files copied
- Files skipped or already backed up
- Files verified
- Files failed
- Total planned bytes
- Total copied bytes
- Final state
- Verification result

## DB-005 - Transactional State Changes

State transitions that mark a canonical content object or session entry as verified shall use database transactions.

A failed database transaction shall not cause unverified content to be presented as verified.
# 25. Web Management Application

## WEB-001 - Local Web Application

The appliance shall host a local web application.

The application shall be accessible from an iPhone connected to the appliance Wi-Fi network.

The application shall not require internet connectivity.

The interface shall use a mobile-first responsive layout.

## WEB-002 - Dashboard

The dashboard shall display:

- Overall appliance state
- Active backup state
- Source media status
- Source logical name
- Source read-only status
- Destination SSD status
- Destination available capacity
- Number of new files
- Number of already backed-up files
- Number of pending files
- Number of verified files
- Number of failed files
- Current backup percentage
- Current file
- Bytes copied
- Total bytes to copy
- Current transfer speed
- Estimated time remaining
- Verification status
- Current warning
- Current error

## WEB-003 - Real-Time Updates

Progress shall update without requiring manual page refresh.

The web application shall use a reconnecting WebSocket event channel for server-pushed state and progress events.

After initial connection or WebSocket reconnection, the client shall retrieve a fresh REST status snapshot before applying subsequent events.

A disconnected or stale web client shall not own backup state.

The web interface shall receive current state from the central backup state model.
## WEB-004 - Backup Controls

The web interface shall support:

- Dry Run
- Start Backup
- Request Backup Cancellation
- Retry Failed Backup
- Resume Interrupted Backup
- Rescan Source
- Re-run Verification
- Safely Remove Source
- Safely Remove SSD
- Shut Down Device
- Reboot Device

System-level and interruption operations shall require confirmation.

## WEB-005 - Start Backup Availability

`Start Backup` shall only be enabled when:

- Source media is valid.
- Source media is read-only.
- Destination SSD is valid.
- Preflight has completed.
- Capacity is sufficient.
- No blocking conflict exists.
- No other backup job is active.

## WEB-006 - Backup History

The web interface shall display previous backup jobs.

For each job the system shall display:

- Backup ID
- Source name
- Date
- Start time
- End time
- Number of files copied
- Number of files skipped
- Number of files failed
- Bytes copied
- Backup state
- Verification result

## WEB-007 - Logs

The web interface shall allow the user to:

- View recent logs
- Filter by severity
- Filter by backup job
- View warnings
- View errors
- Export complete operational logs

Log severities shall include:

```text
INFO
WARNING
ERROR
CRITICAL
```

## WEB-008 - System Status

The web interface shall display:

- System uptime
- CPU temperature
- CPU load
- Memory usage
- System storage capacity
- Destination SSD capacity
- Wi-Fi access point state
- Backup engine state
- Web application state
- Application version
- Power or undervoltage warning state, when available

---

# 26. Physical LED Status

## LED-001 - Physical Status Requirement

The appliance shall provide status communication through a physical LED.

The LED shall communicate sufficient information to perform a normal backup without opening the web application.

## LED-002 - LED Hardware

The implementation shall use a controllable Raspberry Pi status LED where reliable software control is supported by the selected operating system configuration.

The system power indicator shall not be repurposed when doing so would hide hardware power warnings.

When a suitable onboard LED cannot provide reliable application-controlled status, a GPIO-connected external status LED shall be considered required hardware.

The software LED state model shall remain independent of the physical LED implementation.

## LED-003 - LED Protocol

The initial v1 status protocol shall be:

| State | Pattern |
|---|---|
| Booting | Two rapid blinks, repeating |
| Ready | One short heartbeat blink every 3 seconds |
| Source detected | Three short blinks once |
| Preflight | Repeating double blink |
| Copying | Slow pulse |
| Verifying | Repeating long-short pulse |
| Safe to remove source | One long pulse followed by four short blinks |
| Backup completed | Solid for 5 seconds, then safe-to-remove pattern |
| Warning | Three rapid blinks, repeating every 5 seconds |
| Error | Five rapid blinks, repeating |
| Critical system failure | SOS pattern |

## LED-004 - Progress Indication

During an active backup, progress shall periodically be represented by an overlay pattern.

Copy progress shall be calculated from verified-plus-active copied bytes divided by total planned new-content bytes.

File count shall not define the physical LED percentage.

The progress pattern shall use:

```text
Long pulse
Pause
N short blinks
```

Where:

```text
1 blink = at least 25 percent of planned bytes
2 blinks = at least 50 percent of planned bytes
3 blinks = at least 75 percent of planned bytes
4 blinks = copy phase 100 percent of planned bytes
```

The copy progress pattern shall not imply verification completion.

After copy reaches 100 percent, the LED shall display the verification state until the backup is fully verified.
## LED-005 - Authoritative State

The LED controller shall consume backup state from the central backup engine.

The LED service shall not determine backup percentage by independently scanning destination folders.

---

# 27. Power Requirements

## PWR-001 - Qualified Power Configuration

The complete appliance shall be tested with its intended:

- Raspberry Pi
- System storage
- SSD
- SD card reader
- RTC configuration
- Cooling system
- Power cable
- Field power source

The qualified field power source shall sustain the complete appliance during the v1 strict verification workload.

For new content, qualification shall assume approximately four content-size units of data movement across the complete workflow:

1. One source read during strict preflight hashing.
2. One source read while copying and calculating the copy-stream hash.
3. One destination write.
4. One independent destination read for verification.

Additional metadata and already-backed-up source hashing may add further I/O.

Power qualification shall therefore target the real strict-mode workload, not only simultaneous source read and destination write.
## PWR-002 - Power Warning Detection

When system power telemetry exposes an undervoltage or equivalent power warning, the appliance shall record and expose the condition.

The warning shall be visible through:

- Web interface
- Logs

Repeated or persistent power warnings shall generate an appliance warning state.

## PWR-003 - Backup Start Under Unstable Power

When persistent power instability is detected before a backup begins, the system shall warn the user.

The configurable v1 default policy shall prevent automatic backup start under a persistent power warning.

## PWR-004 - Unexpected Power Loss

The application shall assume that power may disappear without warning.

Correctness shall not depend on a graceful shutdown.

The interrupted-backup recovery requirements shall protect backup state after unexpected power loss.

## PWR-005 - UPS Support

A UPS or battery-management HAT may be supported as optional hardware.

UPS integration is not mandatory for version 1.

When UPS telemetry is available, a future implementation may initiate graceful shutdown based on remaining battery state.

---

# 28. Thermal Requirements

## THM-001 - Temperature Monitoring

The appliance shall monitor CPU temperature where system telemetry is available.

The current temperature shall be available through the web interface.

## THM-002 - Thermal Warning

A configurable thermal warning threshold shall be defined.

When exceeded:

- A warning shall be logged.
- The web interface shall display the condition.

## THM-003 - Thermal Reliability

The reference enclosure and cooling configuration shall be validated during the strict v1 workload:

- Full source preflight hashing
- Source copy-stream hashing
- Sustained SSD writes
- Independent destination read-back hashing
- Wi-Fi and web activity

Qualification shall include large photo and large video datasets.

The product shall not be considered field-qualified solely based on idle temperature testing.
# 29. Trusted Time Requirements

## TIME-001 - Trusted Wall Clock

The appliance shall maintain an explicit wall-clock trust state.

Clock states shall include:

```text
CLOCK_UNTRUSTED
CLOCK_RTC
CLOCK_PHONE_SYNCED
CLOCK_NETWORK_SYNCED
```

A dated backup session shall not be created while the appliance is in `CLOCK_UNTRUSTED`.

## TIME-002 - Reference RTC

The qualified Raspberry Pi 4 reference hardware shall include an external RTC.

The installer shall support configuring the selected qualified RTC hardware.

The RTC shall be read during boot and updated after a trusted network or phone time synchronization.

## TIME-003 - Phone Time Synchronization

The mobile web application shall send the iPhone browser wall-clock time and timezone to the appliance after authentication.

The appliance shall compare browser time with system time.

When the appliance clock is untrusted or the configured maximum skew is exceeded, the user shall be shown the proposed correction.

An authenticated time synchronization action shall be available.

After successful synchronization, the clock state shall become `CLOCK_PHONE_SYNCED`.

## TIME-004 - Network Time

When an internet-connected network path is available, the appliance may use the operating system network time synchronization service.

The appliance shall not require network time for field backup operation.

## TIME-005 - Time and File Metadata

Source file modification timestamps shall be treated as source metadata.

Wall-clock correction shall not alter source files or source file timestamps.

Source timestamps shall not be used as proof of content identity.

# 30. Web and Device Security

## SEC-001 - Wi-Fi Authentication

The appliance Wi-Fi access point shall require authentication.

Default Wi-Fi credentials shall not be permanently shared across all appliance installations.

The provisioning workflow shall either:

- Ask the user to set the access-point password, or
- Generate a per-device random password and present it during installation.

## SEC-002 - Web Authentication

The web management application shall require authentication.

The authentication mechanism shall be suitable for a single-user local appliance.

The provisioning workflow shall establish the initial administrator credential.

No universal factory web password shall exist.

## SEC-003 - Session Handling

Authenticated web sessions shall expire after a configurable period of inactivity.

Sensitive administrative actions shall require an authenticated session.

## SEC-004 - VNC Credentials

VNC shall require authentication.

VNC credentials shall not be identical to factory-default credentials.

The installer shall verify that VNC administrative access is not left with a shared default credential.

## SEC-005 - Credential Bootstrap

Interactive installation shall occur before the appliance switches permanently into normal access-point operation.

Before the final reboot, the installer shall display:

- Appliance SSID
- Appliance local hostname
- Appliance fallback IP
- Whether credentials were user-supplied or generated

Generated secrets shall be displayed once in the installer output and stored only in root-readable provisioning state until first successful authenticated administration or explicit credential rotation.

The installer shall not write plaintext secrets to the destination backup hierarchy.

## SEC-006 - Local HTTP Policy

Use of unencrypted HTTP on the isolated appliance network may be permitted in version 1 only as an explicit deployment decision.

The application architecture shall not assume that the web interface is publicly reachable.

Exposure of the management application to external networks is outside the version 1 security model.

The web service shall bind only to explicitly configured appliance interfaces or addresses.
# 31. Logging and Storage Protection

## LOG-001 - Persistent Logging

Operational logs shall persist across reboots.

Logs shall include:

- Media detection
- Mount operations
- Preflight results
- Backup start
- Backup cancellation
- File copy errors
- Verification failures
- Media removal
- Recovery operations
- Power warnings
- Thermal warnings
- Service failures

## LOG-002 - Log Rotation

Logs shall use bounded retention.

A logging failure shall not be allowed to consume all Raspberry Pi system storage.

Log rotation shall be configured.

## LOG-003 - Database Growth

SQLite database growth shall be monitored.

Backup history retention shall be configurable.

Deletion of operational history shall never delete destination backup files.

## LOG-004 - System Storage Protection

The application shall monitor available system storage.

When system storage reaches a configured critical threshold:

- A warning shall be generated.
- Non-essential logging shall be reduced where appropriate.
- New backup jobs may be blocked if application correctness could be affected.

---

# 32. Cancellation Behaviour

## JOB-001 - Graceful Cancellation

A backup cancellation shall be a request to stop safely.

The engine shall:

1. Stop scheduling new files.
2. Finish or safely abort the current file operation.
3. Preserve verified files.
4. Reject incomplete partial files as valid content.
5. Persist job state.
6. Transition to `BACKUP_CANCELLED`.

## JOB-002 - Cancellation History

Cancelled jobs shall remain visible in backup history.

The user shall be able to retry or resume a compatible cancelled job after preflight validation.

---

# 33. Backup Completion Definition

A backup job shall only become:

`BACKUP_COMPLETED`

when:

- Every planned new file has been copied.
- Every copied file has been verified.
- No file remains in a partial state.
- No file remains failed.
- Destination metadata has been persisted.
- SQLite job state has been committed.

When all recoverable files complete but non-blocking warnings remain, the job may become:

`BACKUP_COMPLETED_WITH_WARNINGS`

A job containing an unverified required file shall not be classified as completed.

---

# 34. Failure Scenarios

The implementation shall explicitly test at minimum:

1. Source card inserted before boot.
2. Source card inserted after boot.
3. Source card removed during preflight.
4. Source card removed during copy.
5. Source card removed during verification.
6. Same source snapshot reinserted.
7. Different source card inserted during recovery.
8. Two cards with colliding filesystem serial or label but different source snapshot identities.
9. Destination SSD absent.
10. Wrong SSD inserted.
11. Destination SSD uses a non-ext4 filesystem.
12. Destination SSD removed during copy.
13. Destination SSD becomes full.
14. Insufficient capacity discovered during preflight.
15. Destination session filename collision.
16. Same file content under a different filename.
17. Same filename with different content.
18. Same size and modification time with different content.
19. Corrupt or unreadable source file.
20. Copy-stream hash differs from strict preflight source hash.
21. Destination verification hash mismatch.
22. Web application failure during backup.
23. Wi-Fi client disconnect during backup.
24. Backup engine process crash.
25. Raspberry Pi reboot during copy.
26. Complete unexpected power loss during copy.
27. Complete unexpected power loss after temporary-object fsync but before verification.
28. Power loss after three-way verification but before `PENDING_FINALIZE` commit.
29. Power loss after `PENDING_FINALIZE` commit but before object rename.
30. Power loss after object rename but before directory fsync.
31. Power loss after directory fsync but before final verified-state commit.
32. Destination manifest recovery after interruption.
33. Appliance-local database loss while destination manifest remains intact.
34. System storage nearly full.
35. Persistent power warning.
36. Sustained high CPU temperature.
37. Multiple source devices inserted.
38. User requests cancellation during copy.
39. Clock is untrusted at boot.
40. RTC time materially disagrees with phone time.
41. Web service listens on an unintended interface.
42. Installer rerun on an already provisioned appliance.
43. Installer interrupted before final service activation.
44. GitHub release package checksum or provenance verification fails.
45. Upgrade requires a database migration.
46. Upgrade fails health checks and rollback is required.
# 35. Version 1 Acceptance Criteria

Version 1 shall not be considered complete until the following behaviours are demonstrated:

- Source block device and source filesystem are enforced read-only during normal appliance operation.
- A writable source device or mount blocks backup.
- FAT32 and exFAT source media are supported on the reference hardware.
- Every regular source file is freshly SHA-256 hashed during the backup preflight.
- A deterministic source snapshot identity is generated.
- A dry run identifies content requiring backup.
- Preflight prevents backup when destination capacity is insufficient.
- The configured destination SSD is positively identified.
- A non-ext4 destination is blocked in the v1 correctness profile.
- Previously verified content is not physically recopied.
- Every completed session presents a complete source snapshot view.
- Same filename with different content is not treated as a duplicate.
- Same size and modification time with different content is detected.
- Every new content object passes preflight-source, copy-stream, and independent destination SHA-256 comparison.
- Destination verification performs a close-and-reopen independent read after file synchronization and per-file cache-eviction request where supported.
- Partial objects are never reported as valid backups.
- `PENDING_FINALIZE` state makes the rename-before-commit recovery window reconcilable.
- Power loss does not cause an interrupted file to be marked verified.
- Interrupted jobs can resume at file level.
- Previously verified files survive an interrupted job.
- A wrong USB disk is not silently used as backup destination.
- Source media removal is detected.
- Destination SSD removal is detected.
- Backup state is visible in the web interface.
- Backup progress updates without manual page refresh.
- WebSocket reconnection reconstructs current state from a fresh REST snapshot.
- A backup continues after the iPhone disconnects.
- The physical LED communicates ready, preflight, copy, verification, completion, warning, and error states.
- LED progress milestones are based on bytes, not file count.
- A user can complete the normal field backup workflow without VNC.
- VNC remains available for administration.
- Dated sessions are not created while wall-clock time is untrusted.
- Phone time synchronization can establish trusted time when RTC or network time is unavailable.
- Destination backup correctness does not depend on recent verified-state commits surviving only on Raspberry Pi microSD storage.
- The destination manifest uses WAL mode and synchronous FULL.
- Operational logs persist across restart.
- Log growth cannot consume system storage without bounds.
- A fresh supported Raspberry Pi OS installation can be provisioned through the supported GitHub release installer.
- The installer is idempotent and safe to rerun.
- The installer configures the Wi-Fi access point, application services, VNC administration, persistent state, and initial credentials.
- GitHub Actions CI runs automated quality and software tests for pull requests and protected branches.
- A tagged release produces versioned installable release assets, checksums, and build provenance.
- Hardware-specific release verification runs on qualified Raspberry Pi hardware before a production release is approved.
# 36. Installation and Provisioning Requirements

## INST-001 - Supported Bootstrap Installation

The project shall publish a versioned `install.sh` as a GitHub Release asset.

The documented bootstrap workflow shall support a single shell command equivalent to:

```text
curl -fsSL <GITHUB_RELEASE_INSTALLER_URL> -o /tmp/aethereal-install.sh && sudo bash /tmp/aethereal-install.sh
```

The installer shall install from the selected GitHub Release.

The installer shall not install application code directly from an unpinned `main` branch checkout.

## INST-002 - Installer Responsibilities

The installer shall:

1. Detect supported Raspberry Pi hardware and operating system.
2. Detect CPU architecture.
3. Install required operating-system packages.
4. Download the versioned application release bundle.
5. Verify release checksums.
6. Verify release provenance when the supported verification tooling is available.
7. Create service users and filesystem paths.
8. Install the Python application in an isolated environment.
9. Create or migrate the appliance-local database.
10. Configure the destination-manifest schema when a valid destination is selected.
11. Configure the standalone Wi-Fi access point.
12. Configure static appliance addressing and local hostname resolution.
13. Configure VNC administration.
14. Configure trusted-time support and the selected RTC profile.
15. Configure systemd units.
16. Configure log rotation.
17. Prompt for or generate per-device credentials.
18. Detect candidate destination SSDs and require explicit destination selection.
19. Validate that the selected destination uses ext4.
20. Write validated appliance configuration.
21. Start services in dependency order.
22. Execute local health checks.
23. Display the final connection and credential summary.
24. Request or perform the final reboot required to activate appliance mode.

## INST-003 - Idempotency

The installer shall be safe to rerun.

Rerunning the installer shall not silently:

- Delete destination backups.
- Delete the destination manifest.
- Reset user credentials.
- Change the configured destination SSD.
- Reformat storage.
- Recreate source aliases.

A repeated installation shall converge the appliance toward the requested version and configuration.

## INST-004 - Installation Modes

The installer shall support:

```text
interactive
non-interactive
repair
upgrade
```

Non-interactive installation shall require explicit configuration and secrets through documented files or environment variables.

Secrets shall not be accepted as command-line arguments when doing so would expose them through process listings or shell history.

## INST-005 - Interrupted Installation

Installation changes shall be staged so that interruption before final activation does not leave a partially configured appliance falsely reporting READY.

The installer shall record installation state and support repair on the next invocation.

---

# 37. Software Release and Update Requirements

## REL-001 - Versioned Releases

Application deployment shall use semantic version tags.

A release shall contain at minimum:

- Application wheel or installable package
- Source distribution or source archive
- Versioned appliance release bundle
- `install.sh`
- `SHA256SUMS`
- Release metadata describing application and schema versions

## REL-002 - Release Integrity

Release assets shall be checksummed.

GitHub build provenance attestations shall be generated for release artifacts where supported.

A checksum or provenance-verification failure shall block installation or upgrade.

## REL-003 - Field Appliance Update Model

Field appliances are offline by design.

Version 1 shall use a pull-based or manually supplied release update model.

GitHub Actions shall not require inbound network access to a field appliance.

When temporary internet connectivity is available, an appliance update command may fetch a selected GitHub Release.

An offline release bundle may also be supplied locally.

## REL-004 - Upgrade Safety

Before upgrade, the appliance shall:

1. Confirm that no backup job is active.
2. Record the currently installed application version.
3. Validate release integrity.
4. Inspect required database migrations.
5. Back up appliance-local configuration and database state.
6. Apply application and schema changes.
7. Restart services.
8. Run health checks.

If post-upgrade health checks fail before an irreversible schema boundary, the upgrade mechanism shall roll back to the previously installed application release.

Database migrations shall declare whether they are reversible.

---

# 38. GitHub CI/CD Requirements

## CICD-001 - Pull Request CI

Every pull request shall run automated checks that include at minimum:

- Python formatting and lint checks
- Static type checks
- Unit tests
- Integration tests that do not require physical Raspberry Pi hardware
- SQLite migration tests
- Installer shell linting
- Installer automated tests
- Package build validation

Required CI checks shall gate merge to the protected primary branch.

## CICD-002 - Main Branch CI

Every change merged to the primary branch shall rerun the complete non-hardware CI suite.

CI artifacts such as test results and package builds may be retained as GitHub Actions workflow artifacts.

## CICD-003 - Hardware Verification

The project shall maintain at least one qualified Raspberry Pi self-hosted GitHub Actions runner or an equivalent controlled hardware test target.

Hardware workflows shall be routable using explicit runner labels.

Hardware verification shall include at minimum:

- Source read-only enforcement smoke test
- USB source and destination detection
- ext4 destination validation
- LED control smoke test
- Thermal and undervoltage telemetry availability
- Application service startup
- Basic copy and verification workflow

Destructive fault-injection and power-cut tests may remain manually triggered or lab-controlled rather than executing on every pull request.

## CICD-004 - Release Workflow

A production release workflow shall trigger from an approved semantic version tag or approved release workflow.

The workflow shall:

1. Run or require passing software CI.
2. Require the defined hardware release gate.
3. Build versioned application artifacts.
4. Build the appliance release bundle.
5. Generate `SHA256SUMS`.
6. Generate build provenance attestations where supported.
7. Publish the assets to a GitHub Release.
8. Record the application version and schema version in release metadata.

## CICD-005 - Deployment Scope

For version 1, continuous delivery means automated production of verified, versioned release assets.

It does not mean unattended deployment to field appliances.

A staging Raspberry Pi may be automatically deployed from GitHub Actions for development or release-candidate verification.

Production field appliances shall update only through an explicit local administrative action.

# 39. Version 1 Product Principle

The appliance shall optimise for backup correctness rather than maximum copy speed.

When the system cannot determine with sufficient confidence that:

- The source is protected,
- The destination is valid,
- Capacity is sufficient,
- Copied content has been verified,

the default behaviour shall be to stop or block the backup and clearly report the reason.

The product shall never report a backup as successful merely because file copy operations appeared to finish.
