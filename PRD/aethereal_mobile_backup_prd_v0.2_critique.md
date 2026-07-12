# Critique — Aethereal Mobile Backup Appliance PRD v0.2

**Reviewed document:** `aethereal_mobile_backup_prd_v0.2.md`
**Date:** 2026-07-11
**Reviewer:** Claude Code

---

## Summary

This is an unusually disciplined PRD. The correctness-first principle (§35), the
"engine is the sole state authority" rule (§6/§20), content identity as size +
SHA-256 (§13), the temp-file → flush → verify → atomic-rename → transactional-commit
chain (§18–19), and the explicit 30-scenario failure test list (§33) are all
strong and rare to see spelled out this well.

The points below are about **gaps and unstated assumptions**, not direction.

---

## High-impact gaps

### 1. The destination filesystem is never specified — yet durability guarantees depend on it
COPY-004 (flush before durable) and VER-004 (rename temp→final, flush the directory,
atomic semantics on power loss) all assume POSIX `fsync`-of-directory and atomic
rename durability. exFAT (the natural choice for cross-platform SSD readability) does
**not** provide reliable directory-fsync semantics or the same crash-atomic rename
behavior. ext4/xfs do. This directly governs whether scenarios 22–24 can actually be
satisfied.

**Recommendation:** Mandate ext4/xfs on the SSD for correctness. If cross-platform
readability matters, call that out as an explicit tradeoff rather than leaving it
implicit.

### 2. Source filesystem support and volume identity are underspecified — and weak for the target cameras
SRC-003 defines an `UNSUPPORTED_FILESYSTEM` state but nothing enumerates what *is*
supported. Canon R6 II and DJI cards are exFAT/FAT32, which have no true filesystem
UUID — only a 32-bit volume serial that can collide and changes on reformat. SRC-005
lists UUID "when available"; for the two primary sources it effectively isn't. That
weak identity underpins FILE-003/FILE-004's hash-reuse cache.

**Latent tension:** FILE-002 says timestamp "shall not prove content identity," but
FILE-004 uses (volume + path + size + mtime) to skip re-hashing. Defensible as a
cache-invalidation heuristic, but on FAT's coarse 2-second mtime resolution and weak
volume ID it is riskier than the rest of the doc's rigor.

**Recommendation:** Enumerate supported source filesystems explicitly. Offer a "full
re-hash / trust-nothing" mode that ignores the mtime cache, consistent with §35.

### 3. A backup "session" is not self-contained — and the PRD never says so
DST-004 gives every job its own timestamped session directory, but FILE-005 dedups
`ALREADY_BACKED_UP` against *any* prior verified destination object. So a new session
folder contains only the **new** files; previously-seen content lives in an older
session and is merely referenced by the manifest. Efficient, but it breaks the
intuitive "each session folder = a complete copy of that card" mental model, and
manual deletion of an old session (possible via VNC) silently guts later dedup
references. FILE-005's "record without a valid destination file is insufficient"
preserves correctness, but the product behavior is surprising.

**Recommendation:** State explicitly what a session directory contains. Consider
hardlink/reflink into each session to make sessions self-contained (depends on the
filesystem choice in #1).

### 4. No real-time clock, no NTP — but the whole layout is date-based
The Pi 4 has no RTC and the appliance is offline by design (§2). Yet DST-004 folders
are `YYYY/YYYY-MM-DD/…`, DB-003 stores start/end timestamps, and FILE-004 compares
mtimes. After a power loss the clock can return at epoch or a stale value, producing
wrong folder names and mis-ordered history.

**Recommendation:** Require an RTC HAT or `fake-hwclock`, and/or let the user set the
clock from the phone via the web UI on connect (the phone has correct time even
offline).

### 5. Re-reading the destination may hit the page cache, not the disk
VER-002/VER-003 compute a destination SHA-256 after copy. If that read is served from
RAM, it verifies the buffer, not the bytes that landed on the SSD — exactly the
"userspace write ≠ durable backup" failure COPY-004 exists to prevent.

**Recommendation:** After `fsync`, drop caches or read the destination with `O_DIRECT`
before hashing. State this explicitly.

---

## Medium

### 6. Is the source hashed independently, or from the copy stream?
VER-003 shows "DETERMINE SOURCE SHA-256" as a step but doesn't say whether it is a
second independent read of the card or the hash of the bytes streamed during copy.
Hashing the copy stream proves copy fidelity but not that the card was read correctly;
an independent re-read catches unstable source reads (scenario 16) but doubles source
read time and keeps the card mounted longer. Pick one and document it.

### 7. Recovery rule for the "renamed but not yet committed" window is underspecified
VER-004 orders rename → dir-flush → DB-commit. Scenario 24 (power loss after verify,
before commit) is on the test list — good — but REC-004 says preserve files "confirmed
to exist with the expected content identity," and the expected hash isn't in the
manifest yet in that window. Such a file can't be confirmed and must be re-copied
(fine, it's idempotent). Spell out the reconciliation rule, or write the intended hash
to the DB in a `pending` state before the rename.

### 8. I/O amplification vs. the power/thermal budget
Correctness means: read source, write dest, read dest back (and possibly re-read
source) — up to ~3× the data volume in I/O for the 177 GB example. §35 accepts the
speed hit, but PWR-001 and THM-003 validate "sustained hashing + SSD writes" without
quantifying this amplification. State the expected read-back multiplier so power and
cooling qualification target the real worst case.

### 9. Credential bootstrapping on a screenless, offline, per-device appliance
SEC-001 says Wi-Fi defaults "shall not be permanently shared across all installations,"
and SEC-002/SEC-004 require web and VNC auth. But there is no screen — how does the
user learn the per-device Wi-Fi password and initial web credential the first time?
Sticker? First-boot-generated secret shown where? This onboarding path is missing and
is the one place the security model touches usability.

---

## Minor / nits

- **LED-004 progress:** "25 percent" of *what* — bytes or file count? WEB-002 tracks
  both; specify (bytes is the honest choice for photo media).
- **SRC-008 multiple sources** vs. HW §4's single SD reader — only occurs with a
  hub/multi-slot reader; keep it, but note it's an edge case for the reference
  hardware.
- **Real-time transport (WEB-003)** is unspecified; combined with "backup survives
  client disconnect" (§7) it implies server-push (SSE/WebSocket) with reconnect — worth
  naming.
- **Belt-and-suspenders read-only:** SRC-002 validates the *mount* is ro; setting the
  block device read-only (`blockdev --setro`) before mounting would make SRC-001
  physically enforceable, matching the doc's paranoia elsewhere.
- **No destination scrub / bit-rot re-check** over time. Out of scope is fine, but since
  the manifest stores per-file hashes, note a future scrub is cheap to add.

---

## Priority order for a v0.3 redline

1. Destination filesystem decision (#1) — several other items hinge on it.
2. Source filesystem set + identity + full-rehash mode (#2).
3. Session self-containment behavior (#3).
4. Clock/RTC strategy (#4).
5. Destination cache-bypass on verify (#5).

---

# Review addendum — Implementation Plan v0.1 & Verification Plan v0.1

Both documents are strong and well-aligned with the PRD. The implementation plan's
process separation (backupd / web / led / watch), typed state machine, immutable
plan, and explicit "don't use `shutil.copy2` as the whole abstraction" are all sound.
The verification plan's failure-injection discipline (VP-004), dual filesystem + DB
inspection (VP-002/003), and independent off-appliance hash comparison (Canon test
step 15) are exactly right.

However, **none of the five high-impact PRD gaps above are closed** by either
document, and each plan adds a few issues of its own.

## The five PRD gaps, tracked across all three documents

| PRD gap | Implementation plan | Verification plan |
|---|---|---|
| 1. Destination FS unspecified | Config has `filesystem_uuid` but no FS type; §15 fsyncs dir "where supported" (concedes exFAT won't) | §4 records the FS but never tests its durability |
| 2. Weak source identity / mtime cache | §12 reuses hash on (vol, path, size, mtime); no full-rehash mode | untested (see VER-1) |
| 3. Session not self-contained | §14 confirms it — only NEW files copied, no hardlink/reflink | not addressed |
| 4. No RTC / clock | no time source in config or installer (§5, §28) | no clock test |
| 5. Verify may read page cache | §16 hashes destination without cache-bypass | off-appliance check exists; in-appliance path untested |

## Implementation Plan — additional findings

### IMP-1 (High) — async event loop vs. blocking hashing/copy
backupd is asyncio-based (§2.2). SHA-256 hashing and large-file copies are blocking;
running them on the event loop stalls progress-event publication. `hashlib` releases
the GIL, so a thread/executor pool is a valid fix — but the plan must specify it
rather than leave copy/verify on the loop.

### IMP-2 (High) — the authoritative manifest lives on the Pi SD system card
`database.path = /var/lib/aethereal-backup/aethereal.db` (§5) places the manifest on
the medium most prone to power-loss corruption and wear on a Pi. DB-004's
transactional guarantee is only as good as that card. §6 enables WAL but sets no
`PRAGMA synchronous`. **Recommendation:** set `synchronous=FULL` (at least for the
verified-state commit), qualify the system-storage medium (industrial SD), and note
that recovery correctness depends on it. Consider whether the manifest belongs on more
robust storage.

### IMP-3 (Medium) — schema missing `files_skipped`
`backup_job` (§6) lacks a skipped/already-backed-up count, though PRD DB-003 and
WEB-006 require it. The count exists only on the `preflight` table.

### IMP-4 (Medium) — state-transition map omissions
§7 omits `MULTIPLE_SOURCES_DETECTED`, `SOURCE_PROTECTION_FAILURE`, `RECOVERING`,
`BACKUP_CANCELLING -> BACKUP_CANCELLED`, and `-> SOURCE_SAFE_TO_REMOVE`. Labeled an
"example," but the multiple-source and protection-failure paths are semantically
required and should appear in the authoritative map.

### IMP-5 (Medium) — source-hash provenance at verification is ambiguous
§16 step 1 "Obtain source SHA-256" does not say whether it reuses the preflight hash
or re-reads the card (PRD critique #6). If it reuses the preflight-recorded identity,
the design is sound — a corrupt copy-read still mismatches the destination hash — but
state this explicitly.

### IMP-6 — headless credential provisioning unresolved
Installer step 11 "Create initial administrator credentials" and §27 Wi-Fi setup do
not describe per-device-unique generation or a delivery path to a screenless user
(SEC-001 requires credentials not be shared across installations).

### Nits
- No `schema_version` / meta table, though "explicit migrations" are required (§6).
- Binding the web app only to appliance interfaces (§22) is good and should be a
  verified property (see VER-5).

## Verification Plan — additional gaps

### VER-1 (High) — the mtime/size identity-cache shortcut is untested
The reuse optimization (Impl §12 / PRD FILE-004) is the one place the system trusts
something other than a fresh hash, yet no test exercises it. **Add:** modify a file's
content while preserving size and mtime (trivial within FAT's 2-second resolution) and
confirm the change is not silently skipped.

### VER-2 (High) — destination-filesystem durability is never validated
FI-REC-004/005 assume directory-fsync and crash-atomic rename; on exFAT these may not
hold. §4 records the FS but no test proves it survives the crash window. Add a targeted
power-cut/atomicity test on the actual chosen filesystem.

### VER-3 (Medium) — no clock / RTC test
On a clockless, offline Pi, session-folder dates and history ordering can be wrong
after power loss. Add a test for time behavior across power cycles.

### VER-4 (Medium) — no source-identity-collision test
Two different exFAT cards can share a volume serial/label. Add a "two distinct cards,
colliding identity" test to confirm they are not conflated (protects the FILE-004
cache and recovery source-matching, REC-005/REC-007).

### VER-5 (Low) — web bind-scope untested
SEC tests do not confirm the web app is unreachable on non-appliance interfaces, though
Impl §22 claims it binds only to them.

### Credit
FI-REC-005 already covers the rename-before-commit recovery window flagged in PRD
critique item #7. Independent off-appliance hashing and dual filesystem + DB inspection
are model practices.

---

# Round 2 review — PRD v0.3, Implementation Plan v0.2, Verification Plan v0.2

Reviewed against the revised documents on 2026-07-11. Verified by reading the three
revised files directly, not only the critique-resolution record.

## Resolution confirmed

All five high-impact PRD items and every IMP/VER finding from the first round are
genuinely closed:

- Destination FS: ext4 mandated (DST-004); non-ext4 -> `UNSUPPORTED_DESTINATION_FILESYSTEM`;
  crash-window durability test FI-DST-005 injects power loss at all seven finalization
  boundaries.
- Source identity: strict fresh hashing (FILE-004) + deterministic source snapshot
  identity (SRC-007); tests ST-SRC-006 and ST-FILE-005.
- Session self-containment: canonical content store + hardlinked complete-snapshot
  sessions (DST-005/007).
- Clock: trusted-time model with RTC + phone sync (TIME-001..005); dated sessions
  blocked while `CLOCK_UNTRUSTED`.
- Verify vs cache: fsync -> close -> POSIX_FADV_DONTNEED -> reopen -> independent H3,
  inside a three-way H1==H2==H3 model (COPY-004 / VER-002).
- IMP fixes: worker thread pool; manifest moved to the SSD with WAL + synchronous=FULL;
  `files_skipped`; complete state-transition map; `schema_meta`; bind-scope test;
  `PENDING_FINALIZE` rename-before-commit recovery (VER-004).

Failure scenarios expanded 30 -> 46; traceability matrix rebuilt. Good work.

## New issues introduced by the redesign

### R2-1 (Product, highest) ext4 output SSD is not natively readable on macOS/Windows
§3 makes native cross-platform readability a non-goal to gain Linux durability
semantics. Defensible, but the field tests now inspect "from a separate Linux system."
If the downstream editing/offload machine is a Mac (as here), the backup SSD will not
mount without third-party ext4 software.

**RESOLVED (2026-07-11):** User will reformat the SSD to whatever suits Raspbian and
does not need the SSD to mount on the Mac. ext4 is confirmed as the v1 destination
filesystem. No mitigation needed. Downstream offload from the SSD will happen on Linux
(the Pi itself or another Linux host), not directly on macOS.

### R2-2 (Correctness gap) Intra-job duplicate content collides
Two files with identical content on the same card are both classified `NEW` during one
preflight (the canonical store lacks the object during comparison), so both plan a copy
to the same `<sha256>` object path. The second copy fails on final-path-exists /
exclusive-create (impl §15 steps 2-4). The planner needs within-job dedup: the second
instance must become `LINK_EXISTING` after the first finalizes. Not specified; ST-FILE-001
only tests duplicates across separate jobs.

**RESOLVED (2026-07-11):** Implemented in the planner (`src/aethereal/backup/planner.py`):
the first `NEW` occurrence is `COPY_VERIFY_OBJECT_AND_LINK`; further identical-content
files in the same job are `LINK_NEW_OBJECT_SAME_JOB` and counted once toward capacity.
Documented in Implementation Plan v0.3 section 14; tested in
`tests/unit/test_planner.py::test_intra_job_duplicate_is_linked_not_copied`. The copier
must honour `LINK_NEW_OBJECT_SAME_JOB` (link after the sibling object finalizes) when
that module is built.

### R2-3 (Common-case edge) Zero-new-byte backup
Re-inserting an already-backed-up card is the primary dedup case but yields
`planned_bytes = 0`: progress % and ETA risk divide-by-zero (LED-004 / dashboard), and
the session is pure hardlinks. Needs explicit handling and a test; no ST-PRE/COPY case
covers an all-`ALREADY_BACKED_UP` job.

### R2-4 (Impl validation) Object store and session tree must share a filesystem
Config exposes `object_store_root` and `backup_root` separately; hardlinking across
filesystems fails with `EXDEV`. Destination validation should assert both are on one
mount.

### R2-5 (Workflow) Hardlink sessions drop per-file source mtime on the visible FS
DST-008 concedes this. Photographers often rely on file mtime = capture time when
offloading. Two identical-content files with different mtimes cannot both keep their
mtime on a shared inode; the source timestamp survives only in the manifest, not on the
browsable SSD. Confirm acceptable.

### R2-6 (Field usability) One unreadable file hard-blocks the whole backup
§14 treats any unreadable regular file as blocking. A single corrupt file prevents
backing up thousands of good files. Consider `READY_WITH_WARNINGS` + skip-and-report
instead of a hard block for the field use case.

### R2-7 (Edge) ext4 ~65,000 hardlink-per-inode ceiling
A small identical file recurring across very many sessions can exhaust the link count.
Define a copy fallback when the ceiling is reached.

### Minor
- `PENDING_FINALIZE` authority is split between `content_object.status` and
  `copy_operation.state`; clarify which is authoritative.
- Phone-time sync (TIME-003) is attacker-settable by any authenticated AP client; low
  risk for a single-user local appliance, but worth noting in the security model.

### R2-8 (Correctness) BACKUP_FAILED was an unrecoverable dead end
Found while implementing the state machine from Impl Plan v0.2 section 7:
`BACKUP_FAILED` appeared only as a transition target, never a source, so a failed job
could never retry, reconcile, or release the source — contradicting WEB-004.

**RESOLVED (2026-07-11):** Fix captured in a new **Implementation Plan v0.3** (section 7),
adding `BACKUP_FAILED -> PREFLIGHT_SCANNING` (retry via fresh preflight, PRE-001),
`-> RECOVERY_REQUIRED` (reconcile), and `-> SOURCE_SAFE_TO_REMOVE` (abandon cleanly).
The v0.2 document was restored to its original ChatGPT-authored state; the change lives
only in v0.3. Code and tests match v0.3 (`src/aethereal/backup/state_machine.py`,
`tests/unit/test_state_machine.py`).

### R2-9 (Correctness) PREFLIGHT_BLOCKED was also a dead end
Found while building the engine: like `BACKUP_FAILED`, `PREFLIGHT_BLOCKED` appeared only
as a transition target, so a blocked preflight (insufficient capacity, conflict, or
unreadable file) could never rescan or reset.

**RESOLVED (2026-07-11):** Impl Plan v0.3 section 7 adds
`PREFLIGHT_BLOCKED -> PREFLIGHT_SCANNING` (rescan after freeing space / swapping SSD) and
`-> IDLE` (abandon). PRE-008 forbids overriding a capacity block, not rescanning. Code and
tests match (`state_machine.py`, engine `reset()`, `tests/integration/test_engine.py`).
