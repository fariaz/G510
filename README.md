# g510 — Logitech G510/G510s Linux Driver

[![CI](https://github.com/fariaz/g510/actions/workflows/ci.yml/badge.svg)](https://github.com/fariaz/g510/actions/workflows/ci.yml) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE) [![Ubuntu 24.04](https://img.shields.io/badge/Ubuntu-24.04-E95420?logo=ubuntu)](https://ubuntu.com) [![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python)](https://python.org)

Full Linux driver stack for the **Logitech G510 / G510s** gaming keyboard.

## Features

| Feature | G510 | G510s | Method |
|---|---|---|---|
| G1–G18 macro keys | ✅ | ✅ | evdev → macro engine |
| M1/M2/M3 bank switching | ✅ | ✅ | evdev → profile state |
| MR macro record | ✅ | ✅ | FSM → sequence macros |
| RGB backlight control | ✅ | ✅ | sysfs LEDs or USB HID |
| M-key LEDs | ✅ | ✅ | sysfs or USB HID report 0x04 |
| LCD GamePanel (160×43) | ✅ | ✅ | hidraw, 7-page wire format |
| Media keys | ✅ | ✅ | playerctl / pactl |
| Volume wheel | ⚠️ | ⚠️ | evdev REL_WHEEL (erratic) |
| Mute / mic-mute keys | ✅ | ✅ | pactl |
| Headphone mute LED | — | ✅ | USB HID report 0x04 |
| Mic mute LED | — | ✅ | USB HID report 0x04 |
| Game-mode key (Win lock) | — | ✅ | evdev → game_mode toggle |
| GUI control panel | ✅ | ✅ | GTK3 |
| D-Bus IPC | ✅ | ✅ | org.g510.Daemon |
| Profile manager | ✅ | ✅ | JSON profiles |
| Auto model detection | ✅ | ✅ | lsusb / sysfs PID scan |

## Architecture

```
GUI (GTK3)  ←──D-Bus──→  g510-daemon  ←──evdev──  kernel hid-lg-g15
                              │                              │
                         model.py                    /dev/input/*
                         profiles (JSON)          /sys/class/leds/*
                         libg15 (USB)              /dev/hidraw*
                         Pillow (LCD)
```

## USB product IDs

| PID    | Device                                  |
|--------|-----------------------------------------|
| `c22d` | G510  — keyboard interface              |
| `c22e` | G510  — keyboard + USB audio (headset)  |
| `c24d` | G510s — keyboard interface              |
| `c24e` | G510s — keyboard + USB audio (headset)  |

The daemon auto-detects the model on startup using `lsusb`. Override in config:
```toml
[model]
model = "g510s"   # or "g510" or "auto" (default)
```

## Requirements

- **Linux kernel 5.5+** (for `hid-lg-g15` module; G510 RGB + G-keys)
- **Ubuntu 22.04+** / Debian 12+ recommended
- Python 3.11+
- GTK3 (for GUI)

## Install from .deb (recommended for Ubuntu/Debian)

Pre-built `.deb` packages provide proper system integration: udev rules,
systemd user unit, man pages, and desktop entry.

```bash
# Download the latest release .deb files, then:
sudo dpkg -i g510-daemon_0.1.0-1_all.deb g510-gui_0.1.0-1_all.deb
sudo apt-get install -f          # install any missing dependencies
```

After install:
```bash
systemctl --user enable --now g510-daemon   # autostart at login
g510-verify                                  # check hardware detection
g510-gui                                     # open control panel
```

Log out and back in for group membership (`plugdev`, `input`) to take effect.

To uninstall:
```bash
sudo dpkg -r g510-gui g510-daemon
```

## PPA / apt repository

There is no official PPA yet. Once you set one up (e.g. via Launchpad):
```bash
sudo add-apt-repository ppa:fariaz/g510
sudo apt update
sudo apt install g510-daemon g510-gui
```
Until then, build from source or download the `.deb` from the releases page.

## Build .deb from source

```bash
git clone https://github.com/fariaz/g510
cd g510
bash build-deb.sh               # build current version
bash build-deb.sh 0.2.0         # bump to new version and build
make deb                         # same via Makefile
```

Requirements: `python3`, `dpkg-dev`, `gzip` (all standard on Ubuntu).

## Quick install (from source, no packaging)

```bash
git clone https://github.com/fariaz/g510
cd g510
bash install.sh
```

Then log out/in and:

```bash
bash scripts/g510-verify.sh        # verify hardware detection
systemctl --user start g510-daemon # start daemon
g510-gui                            # open GUI
```

## Manual install

### 1. System dependencies

```bash
sudo apt install python3-pip python3-gi gir1.2-gtk-3.0 \
                 python3-dbus playerctl pulseaudio-utils xdotool usbutils
pip3 install --user evdev Pillow pyusb
```

### 2. udev rules (non-root USB access)

```bash
sudo cp udev/99-logitech-g510.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
sudo usermod -aG plugdev,input $USER
# log out and back in
```

### 3. Run the daemon

```bash
python3 daemon/g510-daemon.py -v
```

### 4. Run the GUI

```bash
python3 gui/g510-gui.py
```

### 5. systemd autostart

```bash
cp systemd/g510-daemon.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now g510-daemon
```

## Configuration

Config file: `~/.config/g510/config.toml`

```toml
[daemon]
input_device_pattern = "/dev/input/by-id/*Logitech*G510*"
hidraw_device = ""        # leave empty for auto-detect

[lcd]
enabled = true
fps = 4
default_screen = "clock"  # clock | sysinfo | custom

[rgb]
method = "sysfs"          # sysfs | usb
default_color = [255, 128, 0]

[macros]
scripts_dir = "~/.config/g510/macros"
keystroke_delay_ms = 20

[profiles]
profiles_dir = "~/.config/g510/profiles"
active_profile = "default"
```

## Macro types

Defined in `~/.config/g510/profiles/default.json`:

```json
"G1": { "type": "shell",     "command": "xterm" }
"G2": { "type": "keystroke", "keys": "ctrl+shift+t" }
"G3": { "type": "text",      "text": "hello@example.com" }
"G4": { "type": "script",    "script": "my-script.sh" }
```

Shell scripts for `type: script` go in `~/.config/g510/macros/` and must be executable.

## LCD screens

| Screen | Description |
|---|---|
| `clock` | HH:MM:SS + date |
| `sysinfo` | CPU %, memory %, time + CPU bar graph |
| `custom` | Text lines from profile config |

## X11 / LXQt

This project targets **X11 desktop environments**, especially LXQt.

- The GUI (`g510-gui`) uses **GTK3** — compatible with LXQt, XFCE, LXDE, MATE, and any X11 desktop with GTK3 support.
- Text macros use **xdotool** (X11 only): `sudo apt install xdotool`
- All other features (G-keys, RGB, LCD, media keys) are desktop-independent and work on any Linux system.

## Uninstall

**From .deb:**
```bash
sudo dpkg -r g510-gui g510-daemon   # remove binaries
sudo dpkg -P g510-gui g510-daemon   # purge including config files
```

**From source (install.sh):**
```bash
systemctl --user disable --now g510-daemon
rm -f ~/.local/bin/g510-daemon ~/.local/bin/g510-ctl ~/.local/bin/g510-gui
sudo rm -f /etc/udev/rules.d/99-logitech-g510.rules
sudo udevadm control --reload-rules
# Optionally remove user config:
rm -rf ~/.config/g510
```

## Troubleshooting

**G-keys not detected:**
```bash
lsmod | grep hid_lg_g15   # must be loaded
sudo modprobe hid-lg-g15
```

**Permission denied on /dev/hidraw* or /dev/input/*:**
```bash
sudo usermod -aG plugdev,input $USER   # then log out/in
```

**RGB not working:**
Check sysfs:
```bash
ls /sys/class/leds/ | grep -i logitech
# If empty, try USB direct in config: method = "usb"
# Requires: pip install pyusb
```

**LCD blank:**
```bash
# Find hidraw device
udevadm info /dev/hidraw* 2>/dev/null | grep -A5 "046d"
# Set it explicitly in config: hidraw_device = "/dev/hidraw0"
```

**Daemon logs:**
```bash
journalctl --user -u g510-daemon -f
# or verbose:
g510-daemon -v
```

## Known issues

- **Volume wheel** is erratic — this is a longstanding issue in the G510 Linux ecosystem. The wheel generates REL_WHEEL events on a separate input device but the direction/speed is unreliable through hid-lg-g15. Direct USB HID polling may improve this.
- **LCD wire format** — the exact HID report structure for the G510 LCD differs from the G15. The packing in `lcd.py` is approximate and may need tuning for your specific keyboard revision.
- **M-key LEDs** — via sysfs these only update when the kernel exposes them as LED class devices (varies by kernel version). USB direct control is more reliable.

## Project structure

```
g510/
├── udev/
│   └── 99-logitech-g510.rules   # udev rules
├── daemon/
│   ├── g510-daemon.py           # main daemon entry point
│   └── g510/
│       ├── config.py            # TOML config loader
│       ├── keyboard.py          # evdev input handler
│       ├── macros.py            # macro execution engine
│       ├── rgb.py               # RGB backlight controller
│       ├── lcd.py               # LCD GamePanel renderer
│       ├── profiles.py          # profile manager
│       └── dbus_iface.py        # D-Bus service
├── gui/
│   └── g510-gui.py              # GTK3 control panel
├── profiles/
│   └── default.json             # default macro profile
├── systemd/
│   └── g510-daemon.service      # systemd user service
├── scripts/
│   └── g510-verify.sh           # hardware detection verifier
└── install.sh                   # one-shot installer
```

## License

MIT
