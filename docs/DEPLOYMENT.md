# Raspberry Pi bring-up

How to deploy the appliance to a Raspberry Pi 4 and take it through a first real backup.
This is a manual bring-up guide; a one-command installer is future work (see the PRD
`INST-*` requirements).

> **Status:** the backup engine, Linux platform layer (read-only mount enforcement,
> device/destination validation, media manager), monitoring, LED pattern model, and web
> UI are implemented and tested. Live udev hotplug monitoring, the GPIO LED runtime loop,
> the Wi-Fi access point, VNC, RTC, and the installer are **not yet automated** — this
> guide sets them up by hand.

---

## 1. Hardware

- Raspberry Pi 4 (64-bit)
- High-endurance microSD for the system
- External USB **SSD** (USB 3 port) — for the backup destination
- USB **SD card reader** (a *separate* USB port) — for the source cards
- (Recommended) DS3231-class **RTC** module — the Pi has no clock and runs offline
- (Optional) a GPIO status **LED** + resistor

Use separate USB ports for the SSD and the card reader; keep the USB-C port for power only.

## 2. Operating system

Flash **Raspberry Pi OS (64-bit, Bookworm)** — it ships Python 3.11, matching the project.
Enable SSH (and Wi-Fi for initial setup) via Raspberry Pi Imager's advanced options.

Update and install tools:

```sh
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y git e2fsprogs dosfstools exfatprogs util-linux
curl -LsSf https://astral.sh/uv/install.sh | sh   # installs uv to ~/.local/bin (or /usr/local/bin)
```

## 3. Prepare the destination SSD (ext4)

The v1 correctness profile **requires ext4** on the destination (hardlink + durability
semantics). If your SSD has a Time Machine partition, keep it (APFS) and format a
**separate** partition for Aethereal as ext4.

```sh
lsblk -o NAME,PATH,FSTYPE,SIZE,MOUNTPOINT      # identify your SSD partition, e.g. /dev/sda1
sudo mkfs.ext4 -L AETHEREAL /dev/sdaX          # format the archive partition ext4
sudo mkdir -p /mnt/backup
sudo mount /dev/sdaX /mnt/backup               # mount it
blkid -s UUID -o value /dev/sdaX               # <-- copy this UUID into the config below
```

To auto-mount at boot, add it to `/etc/fstab` by UUID:

```
UUID=<archive-uuid>  /mnt/backup  ext4  defaults,noatime  0  2
```

## 4. Install the application

```sh
sudo mkdir -p /opt && cd /opt
sudo git clone https://github.com/ilmitch/pi-mobile-photobackup.git
cd pi-mobile-photobackup
sudo uv sync --frozen --extra pi --extra linux   # installs gpiozero/lgpio + pyudev on the Pi
```

## 5. Configure

```sh
sudo mkdir -p /etc/aethereal-backup /var/lib/aethereal-backup /var/log/aethereal-backup
sudo cp config/default.yaml /etc/aethereal-backup/config.yaml
sudo nano /etc/aethereal-backup/config.yaml
```

Set at least:

```yaml
destination:
  filesystem_uuid: "<archive-uuid from step 3>"
  backup_root: /mnt/backup/Aethereal
  object_store_root: /mnt/backup/Aethereal/.aethereal/objects/sha256
  manifest_path: /mnt/backup/Aethereal/.aethereal/manifest.sqlite3
```

Keep `backup_root`, `object_store_root`, and `manifest_path` on the **same filesystem**
(the ext4 partition) — session snapshots use hardlinks, which cannot cross filesystems.

## 6. First run (foreground, over the LAN)

Before wiring the access point, test over your normal network:

```sh
cd /opt/pi-mobile-photobackup
sudo uv run python scripts/run_appliance.py \
  --config /etc/aethereal-backup/config.yaml --host 0.0.0.0 --port 8011
```

From a browser on the same network open `http://<pi-ip>:8011`. You should see the
dashboard. Insert a source card into the USB reader — it should appear as the Source.
Because the Pi clock is untrusted at boot, use **Set time from this device** — this reads
your phone/browser clock and **sets the Pi's system time** (so dated session folders are
correct even without an RTC) — then **Dry Run → Start Backup**.

Verify independently (the ultimate check):

```sh
# pick a file and compare source vs. its copy in the session folder
sha256sum /run/aethereal/source/*/DCIM/100CANON/IMG_XXXX.CR3
find /mnt/backup/Aethereal -name IMG_XXXX.CR3 -exec sha256sum {} \;
```

## 7. Run as a service (auto-start at boot)

```sh
sudo cp systemd/aethereal-appliance.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now aethereal-appliance
systemctl status aethereal-appliance
journalctl -u aethereal-appliance -f          # follow logs
```

The unit binds port 80 so a phone can reach it without a port suffix. It runs as root
because mounting and block-device probing require it (hardening with a dedicated user +
capabilities is a follow-up).

## 8. Remaining appliance setup (manual for now)

These are not yet automated by the app:

- **Wi-Fi access point** — with NetworkManager (Bookworm):
  ```sh
  sudo nmcli con add type wifi ifname wlan0 mode ap con-name aethereal-ap ssid Aethereal-Backup
  sudo nmcli con modify aethereal-ap 802-11-wireless.band bg ipv4.method shared \
    ipv4.addresses 192.168.50.1/24 wifi-sec.key-mgmt wpa-psk wifi-sec.psk "<choose-a-password>"
  sudo nmcli con up aethereal-ap
  ```
  Then reach the appliance at `http://192.168.50.1`. Consider a `.local` hostname via
  Avahi (`backup.local`).
- **RTC (optional)** — you do **not** need an RTC: the *Set time from this device* action
  sets the Pi clock from your phone each session, and Raspberry Pi OS's `fake-hwclock`
  keeps the time roughly sane across reboots. An RTC just avoids re-syncing after a power
  cycle. To use one, enable the DS3231 overlay (`dtoverlay=i2c-rtc,ds3231` in
  `/boot/firmware/config.txt`), install `i2c-tools`, and sync it once from a trusted source.
  Keeping the appliance timezone as **UTC** is simplest (the clock is set in UTC).
- **VNC** — `sudo raspi-config` → Interface Options → VNC, for administration.
- **GPIO LED** — wire an LED to a GPIO pin; the LED pattern engine (`src/aethereal/led/`)
  is implemented, but the runtime loop that drives the pin from engine state is a
  follow-up.

## Troubleshooting

- **Source not detected:** `lsblk -o NAME,PATH,FSTYPE,UUID` — the card must be vfat/exfat
  and not the configured destination.
- **Destination invalid:** confirm the SSD is ext4 and its UUID matches the config
  (`blkid -p -s UUID -o value /dev/sdaX`).
- **Backup blocked on clock:** the clock is untrusted — use *Set time from this device*
  or configure the RTC.
- **Permission errors mounting:** the service must run as root (or with `CAP_SYS_ADMIN`).
