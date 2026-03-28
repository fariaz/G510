"""
g510.macrorec — MR key macro-record mode.

When the user presses MR then a G-key, the daemon enters record mode:
  1. All subsequent keystrokes are captured from the keyboard until
     MR is pressed again (or Escape, or a 10s timeout).
  2. The recorded sequence is saved as a "keystroke_sequence" macro
     on the chosen G-key in the current M-bank.
  3. The LCD shows a recording indicator if available.

This module provides MacroRecorder, consumed by keyboard.py.
"""

import logging
import threading
import time
from typing import Optional, List

log = logging.getLogger(__name__)

# Max recording duration in seconds
RECORD_TIMEOUT = 10.0


class MacroRecorder:
    """
    Finite state machine for MR recording mode.

    States:
      IDLE      — normal operation
      ARMED     — MR was pressed; waiting for target G-key
      RECORDING — capturing keystrokes for target G-key
    """

    STATE_IDLE      = "idle"
    STATE_ARMED     = "armed"
    STATE_RECORDING = "recording"

    def __init__(self, profiles, lcd=None):
        self._profiles = profiles
        self._lcd      = lcd
        self._state    = self.STATE_IDLE
        self._target_key: Optional[str] = None
        self._target_bank: Optional[str] = None
        self._recording: List[dict] = []
        self._lock = threading.Lock()
        self._timeout_timer: Optional[threading.Timer] = None

    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._state == self.STATE_RECORDING

    @property
    def is_armed(self) -> bool:
        with self._lock:
            return self._state == self.STATE_ARMED

    def on_mr_press(self, current_bank: str):
        """Called when MR is pressed."""
        with self._lock:
            if self._state == self.STATE_IDLE:
                self._state = self.STATE_ARMED
                self._target_bank = current_bank
                log.info("Macro record: ARMED — press a G-key to record onto it")
                self._show_lcd("ARMED\nPress G-key")
            elif self._state == self.STATE_ARMED:
                # Second MR press cancels arming
                self._cancel()
                log.info("Macro record: cancelled (MR pressed twice)")
            elif self._state == self.STATE_RECORDING:
                # MR press while recording = stop and save
                self._stop_and_save()

    def on_gkey_press(self, key: str, bank: str) -> bool:
        """
        Called when a G-key is pressed.
        Returns True if the event was consumed by the recorder (don't run normal macro).
        """
        with self._lock:
            if self._state == self.STATE_ARMED:
                self._target_key  = key
                self._target_bank = bank
                self._recording   = []
                self._state = self.STATE_RECORDING
                log.info("Macro record: RECORDING onto %s/%s (press MR or Esc to stop)", key, bank)
                self._show_lcd(f"REC {key}/{bank}\n[MR]=stop")
                self._start_timeout()
                return True   # consume — don't run existing macro
            elif self._state == self.STATE_RECORDING:
                # Record this G-key press as part of the sequence
                self._recording.append({"type": "keystroke", "keys": key})
                return True
        return False

    def on_regular_key(self, key_name: str, with_mods: List[str]):
        """Called for every regular key event while recording."""
        with self._lock:
            if self._state != self.STATE_RECORDING:
                return
            keys = "+".join(with_mods + [key_name]) if with_mods else key_name
            self._recording.append({"type": "keystroke", "keys": keys})

    def on_escape(self):
        """Escape cancels recording without saving."""
        with self._lock:
            if self._state in (self.STATE_ARMED, self.STATE_RECORDING):
                log.info("Macro record: cancelled by Escape")
                self._cancel()

    def _start_timeout(self):
        if self._timeout_timer:
            self._timeout_timer.cancel()
        self._timeout_timer = threading.Timer(RECORD_TIMEOUT, self._on_timeout)
        self._timeout_timer.daemon = True
        self._timeout_timer.start()

    def _on_timeout(self):
        with self._lock:
            if self._state == self.STATE_RECORDING:
                log.warning("Macro record: timed out after %.0fs", RECORD_TIMEOUT)
                self._stop_and_save()

    def _stop_and_save(self):
        """Save the recorded sequence. Must be called with self._lock held."""
        if self._timeout_timer:
            self._timeout_timer.cancel()
            self._timeout_timer = None

        if not self._recording:
            log.info("Macro record: nothing recorded")
            # Reset directly (avoid calling _cancel which re-acquires nothing
            # but is logically separate — keep state clean)
            self._state = self.STATE_IDLE
            self._target_key = None
            self._show_lcd(None)
            return

        # Build a sequence macro action
        action = {
            "type": "sequence",
            "steps": self._recording,
        }
        key  = self._target_key
        bank = self._target_bank

        # Save without holding the lock (profile I/O may block)
        self._state = self.STATE_IDLE
        self._show_lcd(f"SAVED\n{key}/{bank}")

        # Save in a thread to avoid blocking the event loop
        steps = list(self._recording)
        threading.Thread(
            target=self._save_macro,
            args=(key, bank, action),
            daemon=True
        ).start()
        log.info("Macro record: saved %d steps to %s/%s", len(steps), key, bank)
        self._recording = []
        self._target_key = None

    def _save_macro(self, key, bank, action):
        try:
            self._profiles.active.set_macro(key, bank, action)
            self._profiles.save_active()
        except Exception as e:
            log.error("Failed to save recorded macro: %s", e)

    def _cancel(self):
        """Cancel arming or recording. Must be called with self._lock held."""
        if self._timeout_timer:
            self._timeout_timer.cancel()
        self._state = self.STATE_IDLE
        self._target_key = None
        self._recording  = []
        self._show_lcd(None)

    def _show_lcd(self, message: Optional[str]):
        """Show a status message on the LCD (fire-and-forget)."""
        if not self._lcd:
            return
        if message is None:
            return
        lines = message.splitlines()
        try:
            self._lcd.set_screen("custom", lines=lines)
        except Exception:
            pass
