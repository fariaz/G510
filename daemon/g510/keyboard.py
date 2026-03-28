"""
g510.keyboard — reads /dev/input events from the G510 and dispatches them.

The hid-lg-g15 kernel driver exposes:
  - G1–G18  →  KEY_MACRO1–KEY_MACRO18
  - M1/M2/M3 →  KEY_MACRO_PRESET1/2/3
  - MR       →  KEY_MACRO_RECORD_START
  - Media keys: KEY_NEXTSONG, KEY_PREVIOUSSONG, KEY_PLAYPAUSE, KEY_STOPCD
  - Volume wheel: REL_WHEEL on a separate event device
  - Mute / mic mute: KEY_MUTE, KEY_F20
"""

import glob
import logging
import subprocess
import threading
import time
from pathlib import Path

try:
    import evdev
    from evdev import InputDevice, ecodes, categorize
    HAS_EVDEV = True
except ImportError:
    HAS_EVDEV = False
    # Provide stub ecodes so the rest of the module parses at import time
    class _Stubs:
        ecodes = {}   # empty dict so KEY_MAP iteration works
        def __getattr__(self, name): return 0
    ecodes = _Stubs()

if not HAS_EVDEV:
    import warnings
    warnings.warn("python-evdev not installed — keyboard input disabled. pip install evdev")

log = logging.getLogger(__name__)

# Map evdev key codes → human-readable names
GKEY_CODES = {
    ecodes.KEY_MACRO1:  "G1",  ecodes.KEY_MACRO2:  "G2",  ecodes.KEY_MACRO3:  "G3",
    ecodes.KEY_MACRO4:  "G4",  ecodes.KEY_MACRO5:  "G5",  ecodes.KEY_MACRO6:  "G6",
    ecodes.KEY_MACRO7:  "G7",  ecodes.KEY_MACRO8:  "G8",  ecodes.KEY_MACRO9:  "G9",
    ecodes.KEY_MACRO10: "G10", ecodes.KEY_MACRO11: "G11", ecodes.KEY_MACRO12: "G12",
    ecodes.KEY_MACRO13: "G13", ecodes.KEY_MACRO14: "G14", ecodes.KEY_MACRO15: "G15",
    ecodes.KEY_MACRO16: "G16", ecodes.KEY_MACRO17: "G17", ecodes.KEY_MACRO18: "G18",
}

MKEY_CODES = {
    ecodes.KEY_MACRO_PRESET1:     "M1",
    ecodes.KEY_MACRO_PRESET2:     "M2",
    ecodes.KEY_MACRO_PRESET3:     "M3",
    ecodes.KEY_MACRO_RECORD_START: "MR",
}

MEDIA_CODES = {
    ecodes.KEY_NEXTSONG:     "NEXT",
    ecodes.KEY_PREVIOUSSONG: "PREV",
    ecodes.KEY_PLAYPAUSE:    "PLAY",
    ecodes.KEY_STOPCD:       "STOP",
    ecodes.KEY_MUTE:         "MUTE",
    ecodes.KEY_F20:          "MIC_MUTE",
}

# Volume step (%) per wheel click
VOLUME_STEP = 5

# G510s game-mode key candidates — loaded from config at runtime.
# Default 0x1a4=420, 0x248=584. Verify with: evtest /dev/input/eventN
# Override in config: [model] game_mode_keycodes = [420]
_GAME_MODE_KEYCODES: set = {0x1a4, 0x248}   # overwritten in __init__ from config

# G510s game-mode key (disables Win key while active)
KEY_GAME_MODE = "game_mode"

# Input report 4 bit masks (G510s mute LED status)
REPORT4_BACKLIGHT_OFF  = 0x04   # bit 2: LCD/kbd backlight off
REPORT4_HP_MUTE_LED    = 0x08   # bit 3: headphone mute LED on
REPORT4_MIC_MUTE_LED   = 0x10   # bit 4: mic mute LED on


class G510Keyboard:
    def __init__(self, config, macro_engine, rgb, lcd, profiles):
        self.config = config
        self.macro_engine = macro_engine
        self.rgb = rgb
        self.lcd = lcd
        self.profiles = profiles
        self._running = False
        self._devices = []
        self._device_lock = threading.Lock()
        self._current_mbank = "M1"
        self._reconnect_interval = 5   # seconds between reconnect attempts
        self._game_mode = False          # G510s: Win key suppressed when True
        self._bank_changed_cb = None     # set by daemon to fire D-Bus BankChanged signal
        self._game_mode_keycodes = config.game_mode_keycodes  # from [model] config

        # Detect model and capabilities
        from g510.model import detect_model
        self._model, self._caps = detect_model(config.model_hint)

        # Macro recorder (MR key)
        from g510.macrorec import MacroRecorder
        self._recorder = MacroRecorder(profiles, lcd)

    def _find_devices(self):
        """Find all input event devices that belong to the G510."""
        devices = []
        pattern = self.config.input_device_pattern
        candidates = glob.glob(pattern)
        if not candidates:
            candidates = glob.glob("/dev/input/event*")

        for path in candidates:
            try:
                dev = InputDevice(path)
                name = dev.name.lower()
                if any(k in name for k in ["g510", "g15", "logitech gaming"]):
                    log.info("Found keyboard device: %s (%s)", dev.name, path)
                    devices.append(dev)
            except Exception as e:
                log.debug("Skipping %s: %s", path, e)

        if not devices:
            # Check if the issue is permissions — /dev/input exists but we can't read it
            import os
            import grp
            user_groups = [g.gr_name for g in grp.getgrall() if os.environ.get("USER","") in g.gr_mem]
            missing = [g for g in ("plugdev", "input") if g not in user_groups]
            if missing:
                log.warning(
                    "No G510 input devices found. "
                    "Your user may not be in the required groups: %s. "
                    "Run: sudo usermod -aG %s $USER  then log out and back in.",
                    ", ".join(missing), ",".join(missing)
                )
            else:
                log.warning(
                    "No G510 input devices found — is the keyboard plugged in? "
                    "Retrying in %ds. Check: lsusb | grep 046d",
                    self._reconnect_interval
                )
        return devices

    def _handle_key_event(self, event, device):
        """Process a single key event."""
        code = event.code

        if event.type == ecodes.EV_KEY:
            if code in GKEY_CODES:
                key_name = GKEY_CODES[code]
                if event.value == 1:
                    log.debug("G-key: %s (bank %s)", key_name, self._current_mbank)
                    # Let the recorder intercept in armed/recording state
                    if not self._recorder.on_gkey_press(key_name, self._current_mbank):
                        self.macro_engine.execute(key_name, self._current_mbank)
                elif event.value == 0:
                    self.macro_engine.on_release(key_name, self._current_mbank)

            elif code in MKEY_CODES:
                if event.value == 1:
                    self._switch_bank(MKEY_CODES[code])

            elif code in MEDIA_CODES:
                if event.value == 1:
                    self._handle_media(MEDIA_CODES[code])

            # Escape cancels macro recording
            elif code == ecodes.KEY_ESC and event.value == 1:
                if self._recorder.is_armed or self._recorder.is_recording:
                    self._recorder.on_escape()

            # G510s game-mode key — KEY_KBD_LCD_MENU4 (0x1a4) or KEY_KBD_LAYOUT_NEXT
            # Exact keycode varies by kernel version; check with evtest on real hardware.
            # We match any key in the known game-mode range.
            elif code in self._game_mode_keycodes and event.value == 1:
                self._handle_game_mode_key(pressed=True)
            elif code in self._game_mode_keycodes and event.value == 0:
                self._handle_game_mode_key(pressed=False)

        elif event.type == ecodes.EV_REL and code == ecodes.REL_WHEEL:
            self._handle_volume_wheel(event.value)

        # G510s: input report 4 carries mute LED status and backlight state
        elif event.type == ecodes.EV_MSC:
            self._handle_report4(event)

    def _switch_bank(self, bank: str):
        if bank == "MR":
            self._recorder.on_mr_press(self._current_mbank)
            return
        self._current_mbank = bank
        log.info("Bank: %s", bank)
        self.rgb.set_mled(bank)
        if self.lcd:
            self.lcd.notify_bank_change(bank)
        if self._bank_changed_cb:
            try:
                self._bank_changed_cb(bank)
            except Exception as e:
                log.debug("BankChanged callback error: %s", e)

    def set_bank_changed_callback(self, cb):
        """Register a callback fired whenever the M-key bank changes.
        Used by the daemon to emit the D-Bus BankChanged signal."""
        self._bank_changed_cb = cb

    def _handle_media(self, action: str):
        """Handle media keys via playerctl/pactl."""
        cmds = {
            "NEXT":     ["playerctl", "next"],
            "PREV":     ["playerctl", "previous"],
            "PLAY":     ["playerctl", "play-pause"],
            "STOP":     ["playerctl", "stop"],
            "MUTE":     ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"],
            "MIC_MUTE": ["pactl", "set-source-mute", "@DEFAULT_SOURCE@", "toggle"],
        }
        cmd = cmds.get(action)
        if cmd:
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except FileNotFoundError:
                log.debug("Command not found: %s", cmd[0])

    def _handle_report4(self, event):
        """
        Handle G510/G510s input report 4 — LED status byte.

        Bit layout (from hid-lg-g15.c kernel patch):
          bit 2 (0x04): backlight is OFF when set (toggled by light key)
          bit 3 (0x08): headphone mute LED active  (G510s only)
          bit 4 (0x10): mic mute LED active          (G510s only)
        """
        if not HAS_EVDEV:
            return
        val = event.value
        if self._caps.headphone_mute_led:
            hp_muted  = bool(val & REPORT4_HP_MUTE_LED)
            mic_muted = bool(val & REPORT4_MIC_MUTE_LED)
            log.debug("G510s mute LEDs: hp=%s mic=%s", hp_muted, mic_muted)
            if self.rgb:
                self.rgb.set_headphone_mute_led(hp_muted)
                self.rgb.set_mic_mute_led(mic_muted)

    def _handle_game_mode_key(self, pressed: bool):
        """Toggle game mode (G510s Win key suppression) on key press."""
        if not pressed:
            return
        self._game_mode = not self._game_mode
        log.info("Game mode: %s", "ON" if self._game_mode else "OFF")
        if self.lcd:
            msg = "Game mode ON\nWin key off" if self._game_mode else "Game mode OFF"
            self.lcd.set_screen("custom", lines=msg.splitlines())

    def _handle_volume_wheel(self, value: int):
        """
        Handle the G510 volume wheel (REL_WHEEL events).
        value > 0 = scroll up = volume up
        value < 0 = scroll down = volume down

        Note: the G510 wheel is known to be erratic under hid-lg-g15.
        We clamp to ±1 per event to avoid runaway volume jumps.
        """
        direction = 1 if value > 0 else -1
        step = VOLUME_STEP * abs(direction)
        op = f"+{step}%" if direction > 0 else f"-{step}%"
        log.debug("Volume wheel: %s", op)
        try:
            subprocess.Popen(
                ["pactl", "set-sink-volume", "@DEFAULT_SINK@", op],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except FileNotFoundError:
            log.debug("pactl not found — volume wheel has no effect")

    def _poll_device(self, device):
        """Event loop for one input device — reconnects on disconnect."""
        log.debug("Polling: %s", device.path)
        try:
            for event in device.read_loop():
                if not self._running:
                    return
                self._handle_key_event(event, device)
        except OSError as e:
            log.warning("Device lost (%s): %s", device.path, e)
        finally:
            with self._device_lock:
                try:
                    self._devices.remove(device)
                except ValueError:
                    pass
            # Trigger a reconnect scan from the main loop
            log.info("Scheduling reconnect in %ds…", self._reconnect_interval)

    def _start_device_thread(self, dev):
        t = threading.Thread(target=self._poll_device, args=(dev,), daemon=True)
        t.start()
        return t

    def _reconnect_loop(self):
        """Periodically scan for new devices — handles hotplug."""
        while self._running:
            time.sleep(self._reconnect_interval)

            with self._device_lock:
                known_paths = {d.path for d in self._devices}

            candidates = self._find_devices()
            for dev in candidates:
                if dev.path in known_paths:
                    # Already open — close the duplicate fd returned by _find_devices
                    try:
                        dev.close()
                    except Exception:
                        pass
                    continue

                # Genuinely new device (hotplug)
                log.info("Hotplug: new device %s", dev.path)
                with self._device_lock:
                    self._devices.append(dev)
                self._start_device_thread(dev)
                # Re-apply profile state on reconnect
                try:
                    self.rgb.apply(self.profiles.active.rgb)
                    self.rgb.set_mled(self._current_mbank)
                except Exception as e:
                    log.debug("RGB reapply failed: %s", e)

    def run(self):
        self._running = True
        initial_devs = self._find_devices()

        with self._device_lock:
            self._devices = initial_devs

        for dev in initial_devs:
            self._start_device_thread(dev)

        # Start hotplug reconnect watcher
        reconnect_thread = threading.Thread(target=self._reconnect_loop, daemon=True)
        reconnect_thread.start()

        while self._running:
            time.sleep(0.5)

        with self._device_lock:
            for dev in self._devices:
                try:
                    dev.close()
                except Exception:
                    pass

    def stop(self):
        self._running = False
