"""
g510.macros — macro execution engine.

Supported macro types
─────────────────────
  keystroke   Simulate a key combo       {"type":"keystroke","keys":"ctrl+shift+t"}
  text        Type a string              {"type":"text","text":"hello@example.com"}
  shell       Run a shell command        {"type":"shell","command":"xterm"}
  script      Run a file                 {"type":"script","script":"my-script.sh"}
  sequence    Replay a recorded list     {"type":"sequence","steps":[...]}
  hold        Hold a key while pressed   {"type":"hold","keys":"space"}
  toggle      Toggle a command on/off    {"type":"toggle","command_on":"cmd","command_off":"cmd"}
  repeat      Repeat a command N times   {"type":"repeat","command":"cmd","count":3,"delay_ms":100}
"""

import logging
import os
import subprocess
import threading
import time
from pathlib import Path

try:
    import evdev
    from evdev import UInput, ecodes
    HAS_UINPUT = True
    KEY_MAP = {
        k.replace("KEY_", "").lower(): v
        for k, v in ecodes.ecodes.items()
        if k.startswith("KEY_")
    }
    EV_KEY = ecodes.EV_KEY
except Exception:
    HAS_UINPUT = False
    ecodes = None   # type: ignore
    UInput  = None  # type: ignore
    KEY_MAP = {}
    EV_KEY  = 1     # fallback constant (never actually used without uinput)

log = logging.getLogger(__name__)


class MacroEngine:
    def __init__(self, profiles, config):
        self.profiles = profiles
        self.config   = config
        self._uinput  = None
        self._lock    = threading.Lock()
        self._toggles: dict = {}   # "{key}/{bank}" → bool

        if HAS_UINPUT:
            try:
                self._uinput = UInput(name="g510-macro-output")
                log.info("uinput device created")
            except Exception as e:
                log.warning("Could not create uinput device: %s", e)

    # ── Public API ────────────────────────────────────────────────────────────

    def execute(self, key: str, bank: str):
        """Execute the macro bound to key+bank. Runs in a background thread."""
        macro = self.profiles.active.get_macro(key, bank)
        if not macro:
            log.debug("No macro bound to %s/%s", key, bank)
            return
        action_type = macro.get("type", "shell")
        log.info("Macro %s/%s → %s", key, bank, action_type)
        threading.Thread(
            target=self._run_action,
            args=(action_type, macro, f"{key}/{bank}"),
            daemon=True,
        ).start()

    def on_release(self, key: str, bank: str):
        """Called on G-key release — handles hold and toggle macros."""
        macro = self.profiles.active.get_macro(key, bank)
        if not macro:
            return
        action_type = macro.get("type", "")

        if action_type == "hold" and self._uinput:
            code = KEY_MAP.get(macro.get("keys", "").lower())
            if code is not None:
                with self._lock:
                    self._uinput.write(EV_KEY, code, 0)
                    self._uinput.syn()

        elif action_type == "toggle":
            key_id = f"{key}/{bank}"
            with self._lock:
                self._toggles[key_id] = not self._toggles.get(key_id, False)

    def close(self):
        if self._uinput:
            self._uinput.close()

    # ── Dispatcher ────────────────────────────────────────────────────────────

    def _run_action(self, action_type: str, macro: dict, key_id: str = ""):
        try:
            {
                "keystroke": lambda: self._do_keystroke(macro),
                "text":      lambda: self._do_type_text(macro.get("text", "")),
                "shell":     lambda: self._do_shell(macro.get("command", "")),
                "script":    lambda: self._do_script(macro.get("script", "")),
                "sequence":  lambda: self._do_sequence(macro.get("steps", [])),
                "hold":      lambda: self._do_hold_press(macro),
                "toggle":    lambda: self._do_toggle(macro, key_id),
                "repeat":    lambda: self._do_repeat(macro),
            }.get(action_type, lambda: log.warning("Unknown macro type: %s", action_type))()
        except Exception as e:
            log.error("Macro execution error (%s): %s", action_type, e)

    # ── Action implementations ────────────────────────────────────────────────

    def _do_keystroke(self, macro: dict):
        """Simulate a key combo such as ctrl+shift+t."""
        if not self._uinput:
            log.warning("uinput not available — cannot simulate keystrokes")
            return

        modifier_aliases = {
            "ctrl": "leftctrl", "control": "leftctrl",
            "shift": "leftshift",
            "alt": "leftalt",
            "super": "leftmeta", "win": "leftmeta", "meta": "leftmeta",
        }

        parts = [p.strip().lower() for p in macro.get("keys", "").split("+")]
        if not parts:
            return

        mod_codes = []
        for part in parts[:-1]:
            resolved = modifier_aliases.get(part, part)
            code = KEY_MAP.get(resolved)
            if code is not None:
                mod_codes.append(code)

        main_code = KEY_MAP.get(parts[-1])
        if main_code is None:
            log.warning("keystroke: unknown key %r", parts[-1])
            return

        delay = self.config.macros.keystroke_delay_ms / 1000.0
        with self._lock:
            for code in mod_codes:
                self._uinput.write(EV_KEY, code, 1)
            self._uinput.write(EV_KEY, main_code, 1)
            self._uinput.syn()
            time.sleep(delay)
            self._uinput.write(EV_KEY, main_code, 0)
            for code in reversed(mod_codes):
                self._uinput.write(EV_KEY, code, 0)
            self._uinput.syn()

    def _do_hold_press(self, macro: dict):
        """Press a key and hold it (release fires on key-up via on_release)."""
        if not self._uinput:
            return
        code = KEY_MAP.get(macro.get("keys", "").lower())
        if code is None:
            log.warning("hold: unknown key %r", macro.get("keys"))
            return
        with self._lock:
            self._uinput.write(EV_KEY, code, 1)
            self._uinput.syn()

    def _do_toggle(self, macro: dict, key_id: str):
        """Run command_on or command_off based on current toggle state."""
        with self._lock:
            active = self._toggles.get(key_id, False)
        cmd = macro.get("command_on" if not active else "command_off",
                        macro.get("command", ""))
        if cmd:
            self._do_shell(cmd)

    def _do_repeat(self, macro: dict):
        """Repeat a shell command N times with an optional delay between runs."""
        cmd   = macro.get("command", "")
        count = int(macro.get("count", 1))
        delay = macro.get("delay_ms", 100) / 1000.0
        for i in range(count):
            if cmd:
                self._do_shell(cmd)
            if i < count - 1:
                time.sleep(delay)

    def _do_sequence(self, steps: list):
        """Execute a recorded sequence of steps in order."""
        for step in steps:
            step_type = step.get("type", "keystroke")
            if step_type == "keystroke":
                self._do_keystroke(step)
            elif step_type == "shell":
                self._do_shell(step.get("command", ""))
            elif step_type == "text":
                self._do_type_text(step.get("text", ""))
            delay = step.get("delay_ms", self.config.macros.keystroke_delay_ms)
            time.sleep(delay / 1000.0)

    def _do_type_text(self, text: str):
        """Type a string of text via xdotool (X11)."""
        if not text:
            return
        try:
            subprocess.run(
                ["xdotool", "type", "--clearmodifiers", "--", text],
                check=True, timeout=10,
            )
        except FileNotFoundError:
            log.warning("xdotool not found — install it for text macros: sudo apt install xdotool")
        except subprocess.CalledProcessError as e:
            log.error("xdotool failed: %s", e)

    def _do_shell(self, command: str):
        """Fire-and-forget shell command."""
        if not command:
            return
        log.debug("shell: %s", command)
        subprocess.Popen(
            command, shell=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    def _do_script(self, script_name: str):
        """Run an executable script from the macros directory."""
        path = self.config.macros.scripts_dir / script_name
        if not path.exists():
            log.warning("script not found: %s", path)
            return
        if not os.access(path, os.X_OK):
            log.warning("script not executable: %s", path)
            return
        subprocess.Popen(
            str(path), shell=False,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
