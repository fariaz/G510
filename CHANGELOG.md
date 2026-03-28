# Changelog

All notable changes to g510 are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Added
- **G510s full support** — auto-detection via `lsusb`/sysfs; all four USB PIDs
  (`c22d`, `c22e`, `c24d`, `c24e`) in udev rules and detection logic
- `daemon/g510/model.py` — `KeyboardModel` enum, `Capabilities` flags,
  `detect_model()` with lsusb and sysfs fallback, `model_name()` helper
- G510s headphone-mute and mic-mute LED control via USB HID report 0x04
  (`HP_MUTE_BIT = 0x20`, `MIC_MUTE_BIT = 0x40`)
- G510s input-report-4 parsing in `_handle_report4()` — tracks mute LED
  state from the keyboard and syncs it to the RGB controller
- G510s game-mode key (`_handle_game_mode_key`) — toggles Win key suppression
  and shows LCD notification; accessible on G510 too if the event fires
- `[model] model = "auto"|"g510"|"g510s"` config option for forcing model
- `RGBController.set_headphone_mute_led()` / `set_mic_mute_led()` —
  silently ignored on sysfs backend, forwarded to USB direct backend
- `scripts/g510-verify.sh` — completely rewritten; detects all four PIDs,
  reports model name, checks G510s mute LED sysfs nodes, checks all tools
- `tests/test_g510s.py` — 30 tests for PID sets, capabilities, lsusb parsing,
  config hints, mute LED bits, game mode FSM, RGBController delegation
- All G510s tests added to standalone `tests/run_tests.py` runner

### Changed
- `udev/99-logitech-g510.rules` — expanded to all four PIDs; audio interface
  PIDs (`c22e`, `c24e`) now get both `plugdev` and `audio` group rules
- `RGBController.set_power_on_color/set_headphone_mute_led/set_mic_mute_led`
  now use `hasattr()` duck-typing instead of `isinstance()` for testability

### Added (prior)
- `repeat` macro type: run a shell command N times with configurable delay
- `hold` macro type: hold a key while the G-key is physically held down
- `toggle` macro type: alternate between `command_on` and `command_off`
- Shell completion scripts for bash and zsh (`g510-ctl completions bash|zsh`)
- `make completions` target in Makefile

### Changed
- `g510-ctl macro list` now shows unbound keys only when `--all` is passed

---

## [0.1.0] — Initial release

### Architecture
- **Kernel layer** — relies on `hid-lg-g15` (mainline since Linux 5.5); no
  out-of-tree kernel module required
- **Userspace daemon** (`g510-daemon`) — Python, evdev, Pillow; talks to the
  keyboard via `/dev/input` and `/dev/hidraw`
- **GUI** (`g510-gui`) — GTK3 control panel (LXQt/X11)
- **CLI** (`g510-ctl`) — full scriptable interface via D-Bus
- **D-Bus service** — `org.g510.Daemon` on the session bus

### Keyboard features
- **G-keys** G1–G18 with M1/M2/M3 bank switching
- **MR macro record** — press MR then a G-key to enter record mode;
  press MR again or Escape to stop; sequences saved to profile
- **Media keys** — next/prev/play/stop forwarded to playerctl
- **Mute / mic-mute** keys via pactl
- **Volume wheel** — REL_WHEEL events mapped to pactl volume steps
- **Hotplug** — daemon reconnects automatically when keyboard is unplugged
  and replugged

### Backlight
- sysfs backend (hid-lg-g15, `multi_intensity` or per-channel brightness)
- USB direct backend (pyusb, mirrors libg15 HID reports)
- M-key LED exclusive selection (M1/M2/M3 lit one at a time)
- `set_power_on_color()` for persistent startup colour (USB direct only)

### LCD GamePanel (160 × 43 px monochrome)
- Correct 7-page HID wire format (256 bytes per page)
- Built-in screens: **clock**, **sysinfo** (CPU delta + memory), **nowplaying**
  (playerctl, scrolling title, progress bar), **custom** (text lines)
- **BankFlash** — M-key switch name overlaid for 1.5 s then restored
- Screen choice persisted to profile JSON; restored on daemon restart
- LCD preview rendered live in the GUI control panel

### Macro engine
- `keystroke` — simulates key combos via uinput (ctrl+shift+t, etc.)
- `text` — types arbitrary strings via xdotool
- `shell` — fire-and-forget shell commands
- `script` — executable scripts from `~/.config/g510/macros/`
- `sequence` — ordered list of steps (output of MR recorder)
- `hold` — holds a key while the G-key is physically depressed
- `toggle` — alternates between two shell commands
- `repeat` — repeats a command N times

### Profiles
- JSON format, one file per profile in `~/.config/g510/profiles/`
- Atomic save (write to `.tmp`, then rename)
- GUI: create, delete, import (JSON), export (JSON)
- CLI: `g510-ctl profile list|switch|create|delete`

### Configuration
- TOML config at `~/.config/g510/config.toml`
- Auto-generated with defaults on first run
- `[daemon]` `[lcd]` `[rgb]` `[macros]` `[volume]` `[profiles]` sections

### Tooling
- `install.sh` — one-shot install (udev rules, Python deps, systemd service)
- `scripts/g510-verify.sh` — hardware detection / sanity check
- `Makefile` — `test`, `lint`, `fmt`, `package`, `start/stop/restart/logs`
- `tests/run_tests.py` — standalone runner (no pytest needed)
- 33 tests across lcd_wire, profiles, macrorec, LCD, RGB, integration

### Example macro scripts
- `screenshot.sh` — gnome-screenshot / scrot / maim fallback chain
- `mic-toggle.sh` — toggle mic mute with desktop notification
- `sysinfo.sh` — system info desktop notification
