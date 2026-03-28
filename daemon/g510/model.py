"""
g510.model — hardware model detection and capability flags.

G510 family USB product IDs
────────────────────────────
  0xc22d  G510  — keyboard interface (no headset plugged in)
  0xc22e  G510  — keyboard + USB audio interface (headset plugged in)
  0xc24d  G510s — keyboard interface (no headset plugged in)
  0xc24e  G510s — keyboard + USB audio interface (headset plugged in)

The kernel's hid-lg-g15 driver maps both G510 and G510s PIDs to the same
LG_G510 / LG_G510_USB_AUDIO model enum, so evdev/sysfs behaviour is
identical.  The differences that require userspace handling are:

  G510s-only features:
  ─────────────────────
  • Dedicated headphone-mute LED (input report 4, bit 3)
  • Dedicated mic-mute LED      (input report 4, bit 4)
  • Game-mode key (KEY_KBD_LCD_MENU group / disables Win key when active)
  • Single USB cable (G510 used two)
  • Headset audio activates on plug-in (G510s audio PID differs)

  Shared features (G510 and G510s):
  ───────────────────────────────────
  • G1–G18 macro keys
  • M1/M2/M3/MR bank keys
  • Media keys (next/prev/play/stop)
  • Volume wheel (REL_WHEEL, erratic)
  • Mute / mic-mute keys (KEY_MUTE, KEY_F20)
  • RGB backlight (sysfs or USB HID report 0x05)
  • M-key LEDs (USB HID report 0x04)
  • LCD GamePanel 160×43 (hidraw, 7-page HID wire format)
"""

import glob
import logging
import subprocess
from enum import Enum, auto
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

USB_VENDOR = 0x046D

# ── Product IDs ───────────────────────────────────────────────────────────────
class PID:
    G510_KBD        = 0xC22D   # G510 keyboard interface (no audio)
    G510_AUDIO      = 0xC22E   # G510 keyboard + USB audio active
    G510S_KBD       = 0xC24D   # G510s keyboard interface (no audio)
    G510S_AUDIO     = 0xC24E   # G510s keyboard + USB audio active

    ALL_KBD   = {G510_KBD, G510_AUDIO, G510S_KBD, G510S_AUDIO}
    G510_ALL  = {G510_KBD, G510_AUDIO}
    G510S_ALL = {G510S_KBD, G510S_AUDIO}
    AUDIO_PIDS = {G510_AUDIO, G510S_AUDIO}

    @classmethod
    def pid_str(cls, pid: int) -> str:
        return f"{pid:04x}"


# ── Model enum ────────────────────────────────────────────────────────────────
class KeyboardModel(Enum):
    UNKNOWN = auto()
    G510    = auto()   # Original G510
    G510S   = auto()   # G510s (2013 revision)


# ── Capabilities ──────────────────────────────────────────────────────────────
class Capabilities:
    """
    Bitmask-style capability flags derived from the detected model.
    All values are booleans.
    """
    def __init__(self, model: KeyboardModel, audio_active: bool = False):
        self.model        = model
        self.audio_active = audio_active   # USB audio interface present

        # Features present on BOTH G510 and G510s
        self.gkeys        = True   # G1–G18
        self.mkeys        = True   # M1/M2/M3/MR
        self.media_keys   = True
        self.volume_wheel = True
        self.mute_key     = True   # KEY_MUTE  (system audio)
        self.mic_mute_key = True   # KEY_F20   (mic mute, F20 in kernel)
        self.rgb          = True
        self.lcd          = True
        self.m_leds       = True

        # G510s-only
        self.headphone_mute_led = (model == KeyboardModel.G510S)
        self.mic_mute_led       = (model == KeyboardModel.G510S)
        self.game_mode_key      = (model == KeyboardModel.G510S)

    def __repr__(self) -> str:
        extras = []
        if self.headphone_mute_led: extras.append("hp-mute-led")
        if self.mic_mute_led:       extras.append("mic-mute-led")
        if self.game_mode_key:      extras.append("game-mode-key")
        if self.audio_active:       extras.append("audio-active")
        return (f"Capabilities(model={self.model.name}"
                + (f", extras=[{', '.join(extras)}]" if extras else "") + ")")


# ── Detection ─────────────────────────────────────────────────────────────────
def detect_model(config_hint: str = "auto") -> tuple[KeyboardModel, Capabilities]:
    """
    Detect which keyboard is connected.

    config_hint: "auto" | "g510" | "g510s"
      - "auto"  — inspect USB bus via lsusb or sysfs
      - "g510"  — force G510 model regardless of USB info
      - "g510s" — force G510s model regardless of USB info

    Returns (model, capabilities).
    """
    if config_hint.lower() == "g510":
        model = KeyboardModel.G510
        log.info("Model forced to G510 by config")
    elif config_hint.lower() == "g510s":
        model = KeyboardModel.G510S
        log.info("Model forced to G510s by config")
    else:
        model = _detect_from_usb()

    audio_active = _audio_active()
    caps = Capabilities(model, audio_active)
    log.info("Detected: %s, %r", model.name, caps)
    return model, caps


def _detect_from_usb() -> KeyboardModel:
    """Try lsusb, then sysfs, to identify the model."""
    pid = _find_pid_lsusb() or _find_pid_sysfs()
    if pid is None:
        log.warning("Cannot identify G510 model — defaulting to G510")
        return KeyboardModel.UNKNOWN

    if pid in PID.G510S_ALL:
        return KeyboardModel.G510S
    if pid in PID.G510_ALL:
        return KeyboardModel.G510
    return KeyboardModel.UNKNOWN


def _find_pid_lsusb() -> Optional[int]:
    """Parse lsusb output to find a known G510 PID."""
    try:
        out = subprocess.check_output(
            ["lsusb", "-d", f"{USB_VENDOR:04x}:"],
            stderr=subprocess.DEVNULL,
            timeout=3,
        ).decode()
        for line in out.splitlines():
            # Format: "Bus NNN Device NNN: ID 046d:c22d Logitech ..."
            parts = line.split()
            for part in parts:
                if ":" in part:
                    try:
                        vid_str, pid_str = part.split(":")
                        vid = int(vid_str, 16)
                        pid = int(pid_str, 16)
                        if vid == USB_VENDOR and pid in PID.ALL_KBD:
                            log.debug("lsusb found PID 0x%04x", pid)
                            return pid
                    except ValueError:
                        continue
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception) as e:
        log.debug("lsusb detection failed: %s", e)
    return None


def _find_pid_sysfs() -> Optional[int]:
    """Walk /sys/bus/usb/devices to find a known G510 PID."""
    try:
        for dev_dir in Path("/sys/bus/usb/devices").iterdir():
            id_vendor  = dev_dir / "idVendor"
            id_product = dev_dir / "idProduct"
            if not id_vendor.exists():
                continue
            try:
                vid = int(id_vendor.read_text().strip(), 16)
                pid = int(id_product.read_text().strip(), 16)
                if vid == USB_VENDOR and pid in PID.ALL_KBD:
                    log.debug("sysfs found PID 0x%04x at %s", pid, dev_dir)
                    return pid
            except (ValueError, OSError):
                continue
    except Exception as e:
        log.debug("sysfs detection failed: %s", e)
    return None


def _audio_active() -> bool:
    """Check whether the USB audio interface is currently active."""
    try:
        out = subprocess.check_output(
            ["lsusb", "-d", f"{USB_VENDOR:04x}:"],
            stderr=subprocess.DEVNULL, timeout=3,
        ).decode()
        for line in out.splitlines():
            for part in line.split():
                if ":" in part:
                    try:
                        _, pid_str = part.split(":")
                        if int(pid_str, 16) in PID.AUDIO_PIDS:
                            return True
                    except ValueError:
                        continue
    except Exception:
        pass
    return False


def model_name(model: KeyboardModel) -> str:
    return {
        KeyboardModel.G510:   "Logitech G510",
        KeyboardModel.G510S:  "Logitech G510s",
        KeyboardModel.UNKNOWN: "Logitech G510 (model unknown)",
    }.get(model, "Unknown")
