# Aethereal Mobile Backup Appliance

## Critique Resolution Record

**Revision target:** PRD v0.3, Implementation Plan v0.2, Verification Plan v0.2  
**Date:** 2026-07-11

---

# 1. Summary

The external critique was accepted as a substantive architecture review.

The revised design closes the destination-filesystem, source-identity, session semantics, clock, verification read-back, event-loop blocking, manifest durability, schema, state-machine, credential provisioning, and verification-plan gaps.

The installation and software-delivery design was also expanded to make the appliance provisionable from a GitHub Release with an idempotent shell installer and GitHub Actions CI/CD.

---

# 2. High-Impact Critique Decisions

| Critique item | Decision | v0.3 resolution |
|---|---|---|
| Destination filesystem unspecified | Accepted | ext4 required for v1 correctness profile |
| FAT/exFAT source identity weak | Accepted | vfat and exfat explicitly supported; strict fresh source hash; source snapshot identity |
| Session not self-contained | Accepted | canonical content store plus hardlinked complete session snapshot view |
| No RTC / trusted time | Accepted | qualified external RTC plus phone and network time trust model |
| Destination hash may hit page cache | Accepted with modification | fsync, per-file POSIX_FADV_DONTNEED request, close/reopen, independent destination hash; no global cache drop |
| Source hash provenance ambiguous | Accepted | H1 strict preflight hash, H2 copy-stream hash, H3 destination reread hash |
| Rename-before-commit window | Accepted | durable PENDING_FINALIZE record before rename |
| I/O amplification unspecified | Accepted | strict mode explicitly qualified as approximately 4 content-size I/O units for new content |
| Headless credential bootstrap unresolved | Accepted | interactive or generated per-device credentials before AP activation |

---

# 3. Implementation Critique Decisions

| Critique item | Decision | Resolution |
|---|---|---|
| Async loop may block on hashing/copy | Accepted | bounded thread worker pool; asyncio only orchestrates and publishes events |
| Manifest on Pi microSD | Accepted and redesigned | authoritative backup manifest moved to destination SSD; appliance-local DB is non-authoritative |
| Missing files_skipped | Accepted | added to backup_job |
| State-map omissions | Accepted | complete normative transition map added |
| Source-hash provenance ambiguous | Accepted | explicit H1/H2/H3 model |
| Credential provisioning unresolved | Accepted | installer prompts or generates credentials before final AP activation |
| No schema_version metadata | Accepted | schema_meta tables added |
| Web bind scope unverified | Accepted | explicit bind-scope requirement and test |

---

# 4. Verification Critique Decisions

| Critique item | Decision | Resolution |
|---|---|---|
| mtime/size cache shortcut untested | Removed from v1 | strict fresh hashing makes cache shortcut non-normative |
| Destination filesystem durability untested | Accepted | ext4 crash-window power-cut qualification added |
| No clock test | Accepted | RTC, untrusted clock, and phone-sync tests added |
| No source identity collision test | Accepted | colliding observed identity with different snapshot hash test added |
| Web bind scope untested | Accepted | explicit interface bind-scope test added |

---

# 5. Installation Decision

The supported user experience is:

```text
FLASH SUPPORTED RASPBERRY PI OS
        |
        v
RUN ONE RELEASE BOOTSTRAP COMMAND
        |
        v
INSTALLER PREFLIGHT
        |
        v
DOWNLOAD VERSIONED GITHUB RELEASE
        |
        v
VERIFY CHECKSUM / PROVENANCE
        |
        v
PROMPT OR GENERATE CREDENTIALS
        |
        v
CONFIGURE AP / VNC / RTC / SERVICES
        |
        v
SELECT EXISTING EXT4 DESTINATION SSD
        |
        v
HEALTH CHECK
        |
        v
DISPLAY CONNECTION SUMMARY
        |
        v
REBOOT INTO APPLIANCE MODE
```

The installer is idempotent and supports repair and upgrade modes.

The installer never formats the destination SSD automatically.

---

# 6. CI/CD Decision

GitHub Actions is divided into four workflows:

```text
ci.yml
installer.yml
hardware.yml
release.yml
```

Software and installer tests use GitHub-hosted runners.

Hardware smoke tests use a qualified Raspberry Pi 4 self-hosted runner with explicit labels.

Release publication is automated after software, installer, and hardware gates pass.

Field appliances remain explicit-update devices. GitHub does not push unsolicited deployments to offline field units.

Production releases contain installable packages, a release bundle, install.sh, SHA256SUMS, release metadata, and build provenance evidence.
