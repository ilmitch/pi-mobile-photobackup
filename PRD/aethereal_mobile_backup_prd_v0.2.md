# Aethereal Mobile Backup Appliance

## Product Requirements Document

**Version:** 0.2  
**Product status:** v1 definition  
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
- Determine which files require backup.
- Prevent a backup from starting when destination capacity is insufficient.
- Copy source content to an external SSD.
- Verify every copied file.
- Recover safely from interrupted backup operations.
- Avoid unnecessarily copying content already verified on the destination.
- Provide backup status through a physical LED.
- Provide detailed status and controls through a local mobile web application.
- Operate through its own standalone Wi-Fi network.
- Support administrative access through VNC.
- Operate without internet connectivity.
- Maintain persistent backup history and operational logs.

---

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

Interrupted jobs shall resume at file level.

A partially copied file may be recopied from the beginning.

---

# 4. Hardware Assumptions

The reference hardware configuration consists of:

- Raspberry Pi 4
- Raspberry Pi system storage
- External USB SSD
- USB SD card reader
- Suitable field power source
- Raspberry Pi Wi-Fi interface
- Controllable status LED

The external SSD shall use a USB 3 host port.

The SD card reader shall use a separate USB host port.

The Raspberry Pi USB-C connector used for device power shall not be treated as a removable-media host connection.

The system shall be validated with the intended SSD, SD card reader, enclosure, cooling solution, and field power source as a complete hardware configuration.

---

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

Source media shall be mounted read-only before scanning begins.

## SRC-002 - Effective Mount Validation

The backup engine shall verify the effective mount state of the source filesystem.

A backup shall only proceed when the source state is:

`MOUNTED_READ_ONLY`

A writable source mount shall cause the operation to enter:

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

---

# 11. Source Media Identity

## SRC-005 - Source Volume Identity

The system shall collect available source identity information.

Identity attributes shall include, when available:

- Filesystem UUID
- Volume label
- Filesystem type
- Total capacity
- Device identifier
- Device serial identifier

The physical mount path shall not be considered a stable source identity.

## SRC-006 - User Source Name

The web interface shall allow a user-defined logical source name.

Examples:

```text
CANON_CARD_01
CANON_CARD_02
DJI_CARD_01
```

The logical name shall not replace technical media identity.

It shall be stored as metadata associated with the detected volume.

---

# 12. Supported Source Content

## FILE-001 - File Selection Policy

The default backup policy shall copy every regular file contained within configured source roots.

The appliance shall not limit backup to known photographic extensions.

The appliance shall not determine whether a file is valuable.

Canon-specific or DJI-specific file extensions may be displayed as metadata but shall not control the default backup policy.

Directories and filesystem metadata required solely by the source filesystem do not need to be copied as independent content.

Symbolic links and special filesystem objects shall not be followed unless explicitly supported by a future version.

---

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

## FILE-004 - Previously Verified Source Instances

When a source file instance has previously been hashed and the following values remain unchanged:

- Source volume identity
- Relative path
- File size
- Modification timestamp

the backup engine may reuse the previously recorded SHA-256 content identity.

When these values do not match, content identity shall be recalculated.

## FILE-005 - Already Backed Up Definition

A file shall be classified as:

`ALREADY_BACKED_UP`

only when its definitive content identity matches a destination file previously marked:

`VERIFIED`

The SQLite manifest shall identify the verified destination object.

A database record without a corresponding valid destination file shall not be sufficient.

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
- Destination mount state
- Destination write access
- Backup root accessibility
- Available filesystem capacity

A failed destination validation shall block backup.

## DST-003 - Multiple Destination Devices

When multiple writable USB storage devices are detected, the configured destination identity shall remain authoritative.

The system shall not select a destination based solely on connection order or mount path.

---

# 15. Destination Folder Structure

## DST-004 - Backup Session Structure

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

A DJI example may contain:

```text
/Backups/
    /2026/
        /2026-07-11/
            /20260711-002_DJI_CARD_01/
                /DCIM/
                /MISC/
```

## DST-005 - Source Directory Preservation

The complete relative directory structure of backed-up source files shall be preserved inside the backup session directory.

The appliance shall not flatten directory structures.

## DST-006 - Session Naming

Every backup job shall receive a unique backup job ID.

The job ID shall be stable and stored in SQLite.

The folder name shall include:

- Backup date
- Backup sequence or unique job identifier
- Sanitised logical source name

---

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

## PRE-003 - Source Inventory

Preflight shall construct an inventory of candidate source files.

For every file, the system shall collect:

- Relative path
- Filename
- File size
- Modification timestamp, when available
- Source volume identity

The system shall resolve file identity as required to determine whether content is already backed up.

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

- Current temporary copy file
- Application metadata
- SQLite growth
- Operational logs
- Verification-related filesystem operations

The reserve calculation shall be documented.

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

## COPY-001 - Temporary Destination File

File content shall initially be copied to a temporary destination file.

Example:

```text
IMG_8421.CR3.aethereal-partial
```

A partial file shall not be presented as a valid completed backup.

## COPY-002 - Existing File Protection

The backup engine shall not overwrite an existing verified file.

Destination path collisions shall be resolved before content copying begins.

## COPY-003 - Copy State

File copy states shall include:

```text
PLANNED
COPYING
COPIED_PENDING_VERIFICATION
VERIFYING
VERIFIED
FAILED
```

## COPY-004 - Durable File Write

After the file copy completes, the backup engine shall request that file data be flushed to the destination storage stack before verification is considered complete.

The application shall not treat a completed userspace write operation alone as proof of a durable backup.

---

# 19. File Verification

## VER-001 - Mandatory Verification

Every newly copied file shall be cryptographically verified.

Verification shall not be optional in version 1.

## VER-002 - Verification Algorithm

SHA-256 shall be used as the default content verification algorithm.

The source content identity and destination content identity shall match.

## VER-003 - Verification Workflow

The required workflow shall be:

```text
COPY TO TEMPORARY FILE
        |
        v
FLUSH FILE DATA
        |
        v
DETERMINE SOURCE SHA-256
        |
        v
CALCULATE DESTINATION SHA-256
        |
        v
COMPARE
        |
       MATCH
      /     \
    YES      NO
     |        |
     v        v
 FINALISE    ERROR
```

## VER-004 - Successful Verification

After successful verification:

1. The temporary file shall be renamed to the final filename.
2. The destination directory state shall be flushed where supported.
3. The SQLite manifest shall be updated transactionally.
4. The file state shall become `VERIFIED`.

The destination file shall only be considered a successful backup after these operations complete.

## VER-005 - Verification Failure

When source and destination hashes do not match:

- The final destination filename shall not be created.
- The file shall not be marked verified.
- The event shall be logged.
- The backup job shall enter a warning or failed state according to retry policy.

The system shall retry the copy a configurable number of times.

The default retry count shall be:

`2`

After retries are exhausted, the file state shall become:

`FAILED`

The backup result shall not be:

`COMPLETED`

---

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

## REC-002 - Filesystem and Database Reconciliation

Recovery shall inspect both:

- SQLite operational state
- Destination filesystem state

SQLite shall not be treated as the sole source of truth regarding file existence.

The destination filesystem shall not be treated as proof that a file was successfully verified.

## REC-003 - Partial Files

Files ending in the configured temporary suffix shall be considered incomplete unless explicitly associated with an active valid copy operation.

Version 1 shall use file-level recovery.

An interrupted partial file may be removed and recopied from the beginning.

Byte-level continuation of a partial file is not required.

## REC-004 - Verified File Preservation

Files previously recorded as `VERIFIED` and confirmed to exist with the expected content identity shall not be recopied.

An interrupted backup shall therefore resume without unnecessarily recopying previously verified files.

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

# 24. SQLite Operational Manifest

## DB-001 - SQLite Requirement

Version 1 shall use SQLite as the persistent operational manifest.

SQLite shall store operational state and backup history.

The destination filesystem remains authoritative regarding physical file existence.

## DB-002 - Minimum Data Model

The data model shall include concepts equivalent to:

```text
source_volume
backup_job
preflight
source_file
content_identity
destination_file
copy_operation
verification_result
event_log
```

## DB-003 - Backup Job Record

A backup job shall store:

- Backup job ID
- Creation timestamp
- Start timestamp
- End timestamp
- Source identity
- Logical source name
- Destination identity
- Destination session path
- Files discovered
- Files copied
- Files skipped
- Files failed
- Total planned bytes
- Total copied bytes
- Final state
- Verification result

## DB-004 - Transactional State Changes

State transitions that mark a destination file as verified shall use database transactions.

A failed database transaction shall not cause an unverified file to be presented as verified.

---

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

The progress pattern shall use:

```text
Long pulse
Pause
N short blinks
```

Where:

```text
1 blink = at least 25 percent
2 blinks = at least 50 percent
3 blinks = at least 75 percent
4 blinks = copy phase 100 percent
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
- SSD
- SD card reader
- Cooling system
- Power cable
- Field power source

The qualified field power source shall sustain the complete appliance during simultaneous:

- Source reads
- SSD writes
- SHA-256 verification
- Wi-Fi activity
- Web access

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

The reference enclosure and cooling configuration shall be validated during sustained file hashing and SSD write workloads.

The product shall not be considered field-qualified solely based on idle temperature testing.

---

# 29. Web and Device Security

## SEC-001 - Wi-Fi Authentication

The appliance Wi-Fi access point shall require authentication.

Default credentials shall not be permanently shared across all appliance installations.

## SEC-002 - Web Authentication

The web management application shall require authentication.

The authentication mechanism shall be suitable for a single-user local appliance.

## SEC-003 - Session Handling

Authenticated web sessions shall expire after a configurable period of inactivity.

Sensitive administrative actions shall require an authenticated session.

## SEC-004 - VNC Credentials

VNC shall require authentication.

VNC credentials shall not be identical to factory-default credentials.

## SEC-005 - Local HTTP Policy

Use of unencrypted HTTP on the isolated appliance network may be permitted in version 1 only as an explicit deployment decision.

The application architecture shall not assume that the web interface is publicly reachable.

Exposure of the management application to external networks is outside the version 1 security model.

---

# 30. Logging and Storage Protection

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

# 31. Cancellation Behaviour

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

# 32. Backup Completion Definition

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

# 33. Failure Scenarios

The implementation shall explicitly test at minimum:

1. Source card inserted before boot.
2. Source card inserted after boot.
3. Source card removed during preflight.
4. Source card removed during copy.
5. Source card removed during verification.
6. Same source card reinserted.
7. Different source card inserted during recovery.
8. Destination SSD absent.
9. Wrong SSD inserted.
10. Destination SSD removed during copy.
11. Destination SSD becomes full.
12. Insufficient capacity discovered during preflight.
13. Destination filename collision.
14. Same file content under a different filename.
15. Same filename with different content.
16. Corrupt or unreadable source file.
17. Verification hash mismatch.
18. Web application failure during backup.
19. Wi-Fi client disconnect during backup.
20. Backup engine process crash.
21. Raspberry Pi reboot during copy.
22. Complete unexpected power loss during copy.
23. Complete unexpected power loss after file copy but before verification.
24. Power loss after verification but before database commit.
25. SQLite database recovery after interruption.
26. System storage nearly full.
27. Persistent power warning.
28. Sustained high CPU temperature.
29. Multiple source devices inserted.
30. User requests cancellation during copy.

---

# 34. Version 1 Acceptance Criteria

Version 1 shall not be considered complete until the following behaviours are demonstrated:

- Source media is always accessed read-only during normal appliance operation.
- A writable source mount blocks backup.
- A dry run identifies content requiring backup.
- Preflight prevents backup when destination capacity is insufficient.
- Previously verified content is not unnecessarily recopied.
- Same filename with different content is not treated as a duplicate.
- Every newly copied file is SHA-256 verified.
- Partial files are never reported as valid backups.
- Power loss does not cause an interrupted file to be marked verified.
- Interrupted jobs can resume at file level.
- Previously verified files survive an interrupted job.
- The configured destination SSD is positively identified.
- A wrong USB disk is not silently used as backup destination.
- Source media removal is detected.
- Destination SSD removal is detected.
- Backup state is visible in the web interface.
- Backup progress updates without manual page refresh.
- A backup continues after the iPhone disconnects.
- The physical LED communicates ready, preflight, copy, verification, completion, warning, and error states.
- A user can complete the normal field backup workflow without VNC.
- VNC remains available for administration.
- Operational logs persist across restart.
- Log growth cannot consume system storage without bounds.

---

# 35. Version 1 Product Principle

The appliance shall optimise for backup correctness rather than maximum copy speed.

When the system cannot determine with sufficient confidence that:

- The source is protected,
- The destination is valid,
- Capacity is sufficient,
- Copied content has been verified,

the default behaviour shall be to stop or block the backup and clearly report the reason.

The product shall never report a backup as successful merely because file copy operations appeared to finish.
