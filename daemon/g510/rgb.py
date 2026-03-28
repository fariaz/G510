"""
g510.rgb — RGB backlight control for the G510.

Strategy:
  1. Try sysfs LED class (hid-lg-g15 kernel driver, Linux 5.5+)
       - Supports multi-color interface (multi_intensity) on newer kernels
       - Falls back to per-channel brightness files on older kernels
  2. Fall back to direct USB HID control (libg15-style, via pyusb)

M-key LED notes:
  - Sysfs: exposed only on some kernel versions; silently skipped if absent
  - USB direct: reliable, uses feature report 0x04 with bank bitmask
  - Only ONE M-key LED is lit at a time (exclusive selection)
"""

import glob
import logging
import os
from pathlib import Path
from typing import Optional, Tuple, List

log = logging.getLogger(__name__)

Color = Tuple[int, int, int]

# G510 USB IDs
G510_VENDOR    = 0x046d
G510_PRODUCT_A = 0xc22d   # G510
G510_PRODUCT_B = 0xc22e   # G510s

# USB HID report IDs (from hid-lg-g15.c)
REPORT_RGB      = 0x05    # LG_G510_FEATURE_BACKLIGHT_RGB
REPORT_MLED     = 0x04    # LG_G510_FEATURE_M_KEYS_LEDS
REPORT_POWERON  = 0x06    # LG_G510_FEATURE_POWER_ON_RGB

# M-bank → bitmask (byte 1 of report 0x04)
MLED_BITS = {"M1": 0x80, "M2": 0x40, "M3": 0x20, "MR": 0x10}

# G510s headphone / mic mute LED control (USB HID, interface 1)
# Report 0x04, byte 1 also contains mute LED bits:
#   bit 5 (0x20): headphone mute LED
#   bit 6 (0x40): mic mute LED
HP_MUTE_BIT  = 0x20
MIC_MUTE_BIT = 0x40


# ─── sysfs backend ────────────────────────────────────────────────────────────

class SysfsBrightness:
    """
    Control the G510 backlight via /sys/class/leds/ (hid-lg-g15 driver).

    Two kernel interfaces are tried in order:
      1. multi_intensity  — single file, writes "R G B"  (kernel 5.12+)
      2. per-channel      — three separate brightness files, one per colour
    """

    def __init__(self):
        self._all_leds   = self._scan_leds()
        self._kbd_leds   = self._filter_kbd(self._all_leds)
        self._mkey_leds  = self._filter_mkey(self._all_leds)
        self._mc_path    = self._find_multicolor()
        if self._kbd_leds or self._mc_path:
            log.info("sysfs RGB: %d kbd LED(s), multicolor=%s",
                     len(self._kbd_leds), self._mc_path is not None)

    @staticmethod
    def _scan_leds() -> List[Path]:
        patterns = [
            "/sys/class/leds/*logitech*g510*",
            "/sys/class/leds/*g510*",
            "/sys/class/leds/*logitech*kbd*",
        ]
        found = set()
        for pat in patterns:
            found.update(Path(p) for p in glob.glob(pat))
        return list(found)

    @staticmethod
    def _filter_kbd(leds: List[Path]) -> List[Path]:
        return [p for p in leds if any(c in p.name for c in ("red","green","blue","backlight","rgb"))]

    @staticmethod
    def _filter_mkey(leds: List[Path]) -> List[Path]:
        return [p for p in leds if any(c in p.name for c in ("m1","m2","m3","m_key","macro"))]

    def _find_multicolor(self) -> Optional[Path]:
        """Return the multi_intensity file if the kernel exposes it."""
        for led in self._kbd_leds:
            mc = led / "multi_intensity"
            if mc.exists():
                return mc
        return None

    def available(self) -> bool:
        return bool(self._kbd_leds) or self._mc_path is not None

    def set_color(self, r: int, g: int, b: int):
        # Try multi-color interface first (cleanest, one write)
        if self._mc_path and self._mc_path.exists():
            try:
                self._mc_path.write_text(f"{r} {g} {b}\n")
                return
            except OSError as e:
                log.debug("multi_intensity write failed: %s", e)

        # Per-channel fallback: match filename substrings "red", "green", "blue"
        colour_map = {"red": r, "green": g, "blue": b}
        written = set()
        for led in self._kbd_leds:
            for colour, value in colour_map.items():
                if colour in led.name and colour not in written:
                    bright = led / "brightness"
                    try:
                        bright.write_text(str(value) + "\n")
                        written.add(colour)
                    except OSError as e:
                        log.debug("brightness write failed on %s: %s", led, e)

    def set_mled(self, bank: str):
        """Light up the correct M-key LED, turn off the others."""
        bank_num = {"M1": "1", "M2": "2", "M3": "3"}.get(bank)
        for led in self._mkey_leds:
            # Turn this LED on if it matches the bank, off otherwise
            is_active = bank_num and (f"m{bank_num}" in led.name or bank.lower() in led.name)
            bright = led / "brightness"
            try:
                bright.write_text("1\n" if is_active else "0\n")
            except OSError:
                pass


# ─── USB direct backend ───────────────────────────────────────────────────────

class USBDirectControl:
    """
    Direct USB HID feature-report control (mirrors libg15).
    Requires: pip install pyusb

    The G510 uses interface 1 for the gaming-key HID interface.
    Reports are sent as class SET_REPORT requests.
    """

    def __init__(self, vendor: int = G510_VENDOR):
        self._dev       = None
        self._pid       = None
        self._vendor    = vendor
        self._iface     = 1        # gaming interface

        self._mute_led_state = 0   # current mute LED bitmask
        try:
            import usb.core
            import usb.util
            self._usb_core = usb.core
            self._usb_util = usb.util
            self._connect()
        except ImportError:
            log.warning("pyusb not installed — USB direct RGB unavailable (pip install pyusb)")
        except Exception as e:
            log.warning("USB direct connect failed: %s", e)

    def _connect(self):
        for pid in (G510_PRODUCT_A, G510_PRODUCT_B):
            dev = self._usb_core.find(idVendor=self._vendor, idProduct=pid)
            if dev is not None:
                self._pid = pid
                self._dev = dev
                log.info("USB direct: G510 found (PID 0x%04x)", pid)
                self._mute_led_state = 0   # track current mute LED bits
                self._detach_if_needed()
                return
        log.debug("USB direct: G510 not found on USB bus")

    def _detach_if_needed(self):
        """Detach kernel driver from the gaming interface so we can claim it."""
        if self._dev is None:
            return
        try:
            if self._dev.is_kernel_driver_active(self._iface):
                self._dev.detach_kernel_driver(self._iface)
                log.debug("USB: detached kernel driver from interface %d", self._iface)
        except Exception as e:
            log.debug("USB: detach skipped (%s)", e)
        # Set device configuration — required on some Linux systems before
        # ctrl_transfer works (harmless if already configured).
        try:
            self._dev.set_configuration()
        except Exception as e:
            log.debug("USB: set_configuration skipped (%s)", e)

    def _ctrl(self, report_id: int, data: bytes) -> bool:
        """Send a HID SET_FEATURE report. Returns True on success."""
        if self._dev is None:
            return False
        payload = bytes([report_id]) + data
        try:
            self._dev.ctrl_transfer(
                0x21,                    # bmRequestType: host→device, class, interface
                0x09,                    # bRequest: HID SET_REPORT
                0x0300 | report_id,      # wValue: feature report
                self._iface,             # wIndex: gaming interface
                payload,
            )
            return True
        except Exception as e:
            log.error("USB ctrl_transfer (report 0x%02x) failed: %s", report_id, e)
            return False

    def available(self) -> bool:
        return self._dev is not None

    def set_color(self, r: int, g: int, b: int):
        # Report 0x05: [r, g, b, 0x00]
        self._ctrl(REPORT_RGB, bytes([r & 0xFF, g & 0xFF, b & 0xFF, 0x00]))

    def set_power_on_color(self, r: int, g: int, b: int):
        """Set the colour that persists after the keyboard powers on."""
        self._ctrl(REPORT_POWERON, bytes([r & 0xFF, g & 0xFF, b & 0xFF, 0x00]))

    def set_mled(self, bank: str):
        """Activate one M-key LED, deactivate all others."""
        bits = MLED_BITS.get(bank, 0)
        # Report 0x04: [bank_bits, 0x00, 0x00, 0x00]
        self._ctrl(REPORT_MLED, bytes([bits, 0x00, 0x00, 0x00]))

    def set_headphone_mute_led(self, on: bool):
        """Light or extinguish the G510s headphone mute LED."""
        self._set_mute_leds(hp=on, mic=None)

    def set_mic_mute_led(self, on: bool):
        """Light or extinguish the G510s mic mute LED."""
        self._set_mute_leds(hp=None, mic=on)

    def _set_mute_leds(self, hp, mic):
        """
        Send MLED report with mute LED bits updated.
        hp / mic: True = LED on, False = LED off, None = leave unchanged.
        """
        if not self._dev:
            return
        # Preserve current state for unchanged (None) channels
        bits = self._mute_led_state
        if hp is True:   bits |= HP_MUTE_BIT
        elif hp is False: bits &= ~HP_MUTE_BIT
        if mic is True:   bits |= MIC_MUTE_BIT
        elif mic is False: bits &= ~MIC_MUTE_BIT
        self._mute_led_state = bits
        self._ctrl(REPORT_MLED, bytes([bits, 0x00, 0x00, 0x00]))

    def close(self):
        if self._dev is not None:
            try:
                self._usb_util.release_interface(self._dev, self._iface)
            except Exception:
                pass


# ─── Controller (picks backend, exposes unified API) ─────────────────────────

class RGBController:
    """
    Unified RGB controller. Picks sysfs or USB direct automatically,
    or respects the config 'method' setting.
    """

    def __init__(self, config):
        self._cfg    = config.rgb
        self._sysfs  = SysfsBrightness()
        self._usb    = None
        self._backend = None

        explicit_usb = (self._cfg.method == "usb")

        if explicit_usb or not self._sysfs.available():
            self._usb = USBDirectControl()

        if not explicit_usb and self._sysfs.available():
            self._backend = self._sysfs
            log.info("RGB backend: sysfs")
        elif self._usb and self._usb.available():
            self._backend = self._usb
            log.info("RGB backend: USB direct")
        else:
            import os as _os, grp as _grp
            _user = _os.environ.get("USER", "")
            _ugroups = {g.gr_name for g in _grp.getgrall() if _user in g.gr_mem}
            if "plugdev" not in _ugroups:
                log.warning(
                    "RGB: no backend available — user '%s' is not in 'plugdev' group. "
                    "Run: sudo usermod -aG plugdev %s  then log out and back in.", _user, _user
                )
            else:
                log.warning(
                    "RGB: no backend available — "
                    "sysfs LEDs not found (try: sudo modprobe hid-lg-g15) "
                    "and pyusb not installed (sudo apt install python3-usb)."
                )

    # ── Public API ────────────────────────────────────────────────────────────

    def apply(self, rgb_profile: dict):
        """Apply color from a profile dict {'color': [r, g, b]}."""
        color = rgb_profile.get("color", self._cfg.default_color)
        if len(color) >= 3:
            self.set_color(*color[:3])

    def set_color(self, r: int, g: int, b: int):
        r, g, b = _clamp(r), _clamp(g), _clamp(b)
        log.debug("set_color(%d, %d, %d)", r, g, b)
        if self._backend:
            self._backend.set_color(r, g, b)

    def set_mled(self, bank: str):
        """Activate the M-key LED for the given bank (M1/M2/M3/MR)."""
        if self._backend:
            self._backend.set_mled(bank)

    def set_power_on_color(self, r: int, g: int, b: int):
        """Persist the startup colour (USB direct only)."""
        r, g, b = _clamp(r), _clamp(g), _clamp(b)
        if hasattr(self._backend, "set_power_on_color"):
            self._backend.set_power_on_color(r, g, b)
        else:
            log.debug("set_power_on_color: only supported with USB direct backend")

    def set_headphone_mute_led(self, on: bool):
        """G510s: light or extinguish the dedicated headphone mute LED."""
        if hasattr(self._backend, "set_headphone_mute_led"):
            self._backend.set_headphone_mute_led(on)
        # sysfs backend has no mute LED control — silently ignored

    def set_mic_mute_led(self, on: bool):
        """G510s: light or extinguish the dedicated mic mute LED."""
        if hasattr(self._backend, "set_mic_mute_led"):
            self._backend.set_mic_mute_led(on)

    def close(self):
        if isinstance(self._backend, USBDirectControl):
            self._backend.close()

    @property
    def backend_name(self) -> str:
        if self._backend is None:
            return "none"
        name = type(self._backend).__name__
        if "Sysfs" in name:
            return "sysfs"
        if "USB" in name:
            return "usb"
        # Fallback: check for duck-typed attributes
        if hasattr(self._backend, "set_power_on_color"):
            return "usb"
        if hasattr(self._backend, "_find_leds"):
            return "sysfs"
        return "unknown"


def _clamp(v: int) -> int:
    return max(0, min(255, int(v)))
