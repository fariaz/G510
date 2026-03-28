# Contributing to g510

Thanks for wanting to improve this project. Here is everything you need to know.

## Project layout

```
g510/
├── daemon/
│   ├── g510-daemon.py      Main entry point
│   ├── g510-ctl.py         CLI tool
│   └── g510/
│       ├── config.py       TOML config loader
│       ├── keyboard.py     evdev input handler + hotplug
│       ├── macros.py       Macro execution engine
│       ├── macrorec.py     MR record-mode FSM
│       ├── lcd.py          LCD screen manager + built-in screens
│       ├── lcd_wire.py     HID wire format encoder
│       ├── rgb.py          RGB backlight controller
│       ├── profiles.py     Profile CRUD + JSON serialisation
│       └── dbus_iface.py   D-Bus service
├── gui/
│   └── g510-gui.py         GTK3 control panel (LXQt/X11)
├── tests/
│   ├── conftest.py         Shared pytest fixtures
│   ├── run_tests.py        Standalone runner (no pytest required)
│   ├── test_g510.py        Core module tests
│   ├── test_macrorec.py    MacroRecorder FSM tests
│   └── test_new_features.py  LCD, RGB, volume, hotplug tests
├── udev/                   udev rules
├── systemd/                systemd user service
├── profiles/               Default profile + example macro scripts
├── scripts/                g510-verify.sh
├── Makefile
└── install.sh
```

## Development setup

```bash
# Clone and enter
git clone https://github.com/fariaz/g510
cd g510

# Install deps
make install-deps

# Verify hardware
make verify

# Run tests (no hardware needed)
make test

# Start daemon in verbose foreground mode
make daemon-debug

# Open GUI
make gui
```

## Running tests

Tests require no hardware and no root. They mock all hardware calls.

```bash
# With pytest (preferred)
PYTHONPATH=daemon pytest tests/ -v

# Without pytest
python3 tests/run_tests.py

# Filter to one module
python3 tests/run_tests.py macrorec
```

## Adding a new macro type

1. Add the type name to the `MACRO_TYPES` list in `gui/g510-gui.py` and
   `MACRO_TYPE_KEYS` in `daemon/g510-ctl.py`.
2. Add a `_do_<type>` method in `MacroEngine` (`daemon/g510/macros.py`).
3. Register it in `_run_action()`'s dispatch dict.
4. Update the docstring at the top of `macros.py`.
5. Add at least one test in `tests/test_g510.py`.

## Adding a new LCD screen

1. Subclass `LCDScreen` in `daemon/g510/lcd.py`.  Implement `render() -> Image`.
2. Register the screen name in `LCDManager.set_screen()` and `_init_screens()`.
3. Expose it in `g510-ctl lcd` (add to `LCD_SCREENS` in `g510-ctl.py`).
4. Add it to the GUI's `_build_lcd_page()` screen list.

## Wire format notes

The G510 LCD uses a 7-page HID report format. Each page is 256 bytes:

```
Byte 0    Report ID = 0x03
Byte 1    0x00
Byte 2    Page index (0–6)
Byte 3    0x00
Bytes 4–163  160 column bytes
             bit 0 = topmost pixel row of this page
             bit 6 = 7th pixel row (or unused in page 6)
             bit 7 = always 0
```

43 rows ÷ 7 rows/page = 6 full pages + 1 partial = **7 pages total**.
See `lcd_wire.py` for the encoder and its tests.

## RGB backend selection

The daemon tries sysfs first, then USB direct:

```
sysfs  →  /sys/class/leds/  (hid-lg-g15, kernel 5.5+)
           multi_intensity file  (kernel 5.12+, one write: "R G B")
           per-channel files     (older kernels, three writes)

usb    →  pyusb ctrl_transfer to interface 1
           report 0x05 = backlight RGB
           report 0x04 = M-key LEDs (exclusive, bitmask)
           report 0x06 = power-on RGB (persists across reboots)
```

Force USB direct in `~/.config/g510/config.toml`:
```toml
[rgb]
method = "usb"
```

## Code style

- Python 3.11+, standard library preferred
- Max line length 100 (configured in `Makefile` lint target)
- `make fmt` runs black; `make lint` runs flake8
- No type stubs needed — inline `# type: ignore` for hardware mocks
- All public methods need a one-line docstring minimum

## Submitting changes

1. Fork the repository and create a feature branch.
2. Run `make test` — all tests must pass.
3. Run `make lint` — zero warnings.
4. Update `CHANGELOG.md` under `[Unreleased]`.
5. Open a pull request with a clear description of what changed and why.

## Known hardware quirks

| Quirk | Status | Notes |
|---|---|---|
| Volume wheel erratic | Open | REL_WHEEL events unreliable through hid-lg-g15; USB polling may help |
| G510s mute LEDs via sysfs | Untested | May not be exposed; USB direct is reliable |
| G510s game-mode key evdev code | Needs hardware | KEY code TBD; check with `evtest` on real hardware |
| M-key LEDs missing in sysfs | Kernel-dependent | USB direct is more reliable |
| LCD wire format varies | Possibly | Page count confirmed 7; byte order unverified on G510s |
| Audio device sharing USB | Works | G510 has built-in USB audio; handled by separate udev rule |

## Reporting bugs

Please include the output of `make verify` and `journalctl --user -u g510-daemon -n 50`.
