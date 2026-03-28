"""
tests/test_macrorec.py — tests for the MR macro-record state machine.

Tests every state transition, timeout, save, cancellation, and edge case.
"""
import sys
import time
import threading
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, str(Path(__file__).parent.parent / "daemon"))

import pytest
from g510.macrorec import MacroRecorder, RECORD_TIMEOUT


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def profiles(tmp_path):
    from g510.profiles import ProfileManager
    pm = ProfileManager(tmp_path / "profiles")
    pm.load_active("default")
    return pm


@pytest.fixture
def lcd():
    m = MagicMock()
    m.set_screen = MagicMock()
    return m


@pytest.fixture
def rec(profiles, lcd):
    return MacroRecorder(profiles, lcd)


# ─── Initial state ────────────────────────────────────────────────────────────

class TestInitialState:
    def test_starts_idle(self, rec):
        assert rec._state == MacroRecorder.STATE_IDLE

    def test_not_recording_initially(self, rec):
        assert not rec.is_recording

    def test_not_armed_initially(self, rec):
        assert not rec.is_armed


# ─── IDLE → ARMED ─────────────────────────────────────────────────────────────

class TestArming:
    def test_mr_press_arms_recorder(self, rec):
        rec.on_mr_press("M1")
        assert rec.is_armed

    def test_armed_sets_target_bank(self, rec):
        rec.on_mr_press("M2")
        assert rec._target_bank == "M2"

    def test_armed_shows_lcd_message(self, rec, lcd):
        rec.on_mr_press("M1")
        lcd.set_screen.assert_called()

    def test_second_mr_cancels_arm(self, rec):
        rec.on_mr_press("M1")
        rec.on_mr_press("M1")
        assert rec._state == MacroRecorder.STATE_IDLE
        assert not rec.is_armed


# ─── ARMED → RECORDING ───────────────────────────────────────────────────────

class TestStartRecording:
    def test_gkey_while_armed_starts_recording(self, rec):
        rec.on_mr_press("M1")
        consumed = rec.on_gkey_press("G3", "M1")
        assert consumed
        assert rec.is_recording

    def test_recording_sets_target_key(self, rec):
        rec.on_mr_press("M1")
        rec.on_gkey_press("G5", "M1")
        assert rec._target_key == "G5"

    def test_recording_empties_buffer(self, rec):
        rec.on_mr_press("M1")
        rec.on_gkey_press("G1", "M1")
        assert rec._recording == []

    def test_gkey_in_idle_not_consumed(self, rec):
        consumed = rec.on_gkey_press("G1", "M1")
        assert not consumed

    def test_gkey_while_recording_captured(self, rec):
        rec.on_mr_press("M1")
        rec.on_gkey_press("G1", "M1")   # start recording on G1
        consumed = rec.on_gkey_press("G2", "M1")  # G2 recorded as step
        assert consumed
        assert any(s.get("keys") == "G2" for s in rec._recording)


# ─── RECORDING → IDLE (save) ─────────────────────────────────────────────────

class TestStopAndSave:
    def test_mr_while_recording_saves(self, rec, profiles):
        rec.on_mr_press("M1")
        rec.on_gkey_press("G4", "M1")
        rec.on_regular_key("a", [])
        rec.on_regular_key("b", ["ctrl"])
        rec.on_mr_press("M1")           # stop
        time.sleep(0.1)                 # let save thread run
        assert rec._state == MacroRecorder.STATE_IDLE
        macro = profiles.active.get_macro("G4", "M1")
        assert macro is not None
        assert macro["type"] == "sequence"
        assert len(macro["steps"]) == 2

    def test_saved_macro_has_correct_steps(self, rec, profiles):
        rec.on_mr_press("M1")
        rec.on_gkey_press("G7", "M1")
        rec.on_regular_key("x", [])
        rec.on_regular_key("y", ["shift"])
        rec.on_mr_press("M1")
        time.sleep(0.1)
        macro = profiles.active.get_macro("G7", "M1")
        steps = macro["steps"]
        assert steps[0] == {"type": "keystroke", "keys": "x"}
        assert steps[1] == {"type": "keystroke", "keys": "shift+y"}

    def test_empty_recording_does_not_save(self, rec, profiles):
        # Use M2 bank which has no default bindings
        rec.on_mr_press("M2")
        rec.on_gkey_press("G6", "M2")
        # Record nothing, then stop
        rec.on_mr_press("M2")
        time.sleep(0.1)
        macro = profiles.active.get_macro("G6", "M2")
        assert macro is None

    def test_state_is_idle_after_save(self, rec):
        rec.on_mr_press("M1")
        rec.on_gkey_press("G1", "M1")
        rec.on_regular_key("a", [])
        rec.on_mr_press("M1")
        time.sleep(0.1)
        assert rec._state == MacroRecorder.STATE_IDLE
        assert not rec.is_recording


# ─── Escape cancellation ─────────────────────────────────────────────────────

class TestEscape:
    def test_escape_while_armed_cancels(self, rec):
        rec.on_mr_press("M1")
        rec.on_escape()
        assert rec._state == MacroRecorder.STATE_IDLE

    def test_escape_while_recording_cancels(self, rec, profiles):
        # Use M2 bank which has no default bindings
        rec.on_mr_press("M2")
        rec.on_gkey_press("G2", "M2")
        rec.on_regular_key("z", [])
        rec.on_escape()
        time.sleep(0.1)
        assert rec._state == MacroRecorder.STATE_IDLE
        # Nothing should have been saved
        assert profiles.active.get_macro("G2", "M2") is None

    def test_escape_while_idle_is_noop(self, rec):
        rec.on_escape()     # must not raise
        assert rec._state == MacroRecorder.STATE_IDLE


# ─── Timeout ─────────────────────────────────────────────────────────────────

class TestTimeout:
    def test_timeout_saves_recorded_steps(self, rec, profiles):
        rec.on_mr_press("M1")
        rec.on_gkey_press("G8", "M1")
        rec.on_regular_key("q", [])
        # Force immediate timeout
        with rec._lock:
            rec._target_key = "G8"
        rec._on_timeout()
        time.sleep(0.1)
        macro = profiles.active.get_macro("G8", "M1")
        assert macro is not None
        assert macro["type"] == "sequence"

    def test_timeout_resets_to_idle(self, rec):
        rec.on_mr_press("M1")
        rec.on_gkey_press("G9", "M1")
        rec._on_timeout()
        time.sleep(0.1)
        assert rec._state == MacroRecorder.STATE_IDLE

    def test_timeout_empty_recording_cancels_cleanly(self, rec):
        rec.on_mr_press("M1")
        rec.on_gkey_press("G10", "M1")
        # _recording is empty → _stop_and_save calls _cancel
        rec._on_timeout()
        time.sleep(0.1)
        assert rec._state == MacroRecorder.STATE_IDLE


# ─── on_regular_key ───────────────────────────────────────────────────────────

class TestRegularKey:
    def test_regular_key_recorded_without_mods(self, rec):
        rec.on_mr_press("M1")
        rec.on_gkey_press("G1", "M1")
        rec.on_regular_key("a", [])
        assert rec._recording == [{"type": "keystroke", "keys": "a"}]

    def test_regular_key_recorded_with_single_modifier(self, rec):
        rec.on_mr_press("M1")
        rec.on_gkey_press("G1", "M1")
        rec.on_regular_key("c", ["ctrl"])
        assert rec._recording == [{"type": "keystroke", "keys": "ctrl+c"}]

    def test_regular_key_recorded_with_multiple_modifiers(self, rec):
        rec.on_mr_press("M1")
        rec.on_gkey_press("G1", "M1")
        rec.on_regular_key("t", ["ctrl", "shift"])
        assert rec._recording == [{"type": "keystroke", "keys": "ctrl+shift+t"}]

    def test_regular_key_ignored_when_idle(self, rec):
        rec.on_regular_key("a", [])   # must not raise or record
        assert rec._recording == []

    def test_regular_key_ignored_when_armed(self, rec):
        rec.on_mr_press("M1")
        rec.on_regular_key("a", [])
        assert rec._recording == []   # still in ARMED, no target key


# ─── Multi-bank recording ─────────────────────────────────────────────────────

class TestMultiBankRecording:
    def test_records_onto_different_bank(self, rec, profiles):
        rec.on_mr_press("M2")
        rec.on_gkey_press("G3", "M2")
        rec.on_regular_key("p", [])
        rec.on_mr_press("M2")
        time.sleep(0.1)
        macro = profiles.active.get_macro("G3", "M2")
        assert macro is not None

    def test_second_recording_overwrites_first(self, rec, profiles):
        # First recording
        rec.on_mr_press("M1")
        rec.on_gkey_press("G1", "M1")
        rec.on_regular_key("a", [])
        rec.on_mr_press("M1")
        time.sleep(0.1)

        # Second recording on same key
        rec.on_mr_press("M1")
        rec.on_gkey_press("G1", "M1")
        rec.on_regular_key("b", [])
        rec.on_regular_key("c", [])
        rec.on_mr_press("M1")
        time.sleep(0.1)

        macro = profiles.active.get_macro("G1", "M1")
        steps = macro["steps"]
        assert len(steps) == 2
        assert steps[0]["keys"] == "b"
        assert steps[1]["keys"] == "c"


# ─── Thread safety ───────────────────────────────────────────────────────────

class TestThreadSafety:
    def test_concurrent_mr_presses_do_not_corrupt_state(self, profiles):
        lcd = MagicMock()
        rec = MacroRecorder(profiles, lcd)
        errors = []

        def press_mr():
            try:
                for _ in range(20):
                    rec.on_mr_press("M1")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=press_mr) for _ in range(5)]
        for t in threads: t.start()
        for t in threads: t.join(timeout=2)

        assert not errors
        assert rec._state in (
            MacroRecorder.STATE_IDLE,
            MacroRecorder.STATE_ARMED,
            MacroRecorder.STATE_RECORDING,
        )


# ─── Sequence macro engine integration ───────────────────────────────────────

class TestSequenceMacroExecution:
    def test_sequence_type_executes_steps(self, tmp_path):
        from g510.config import Config
        from g510.profiles import ProfileManager, Profile
        from g510.macros import MacroEngine

        cfg = Config(tmp_path / "c.toml")
        pm  = ProfileManager(tmp_path / "p")
        pm.load_active()

        macro = {
            "type": "sequence",
            "steps": [
                {"type": "shell", "command": "true"},
                {"type": "shell", "command": "true"},
            ]
        }
        pm.active.set_macro("G1", "M1", macro)

        with patch("g510.macros.UInput", MagicMock()):
            engine = MacroEngine(pm, cfg)
        engine._uinput = None

        with patch.object(engine, "_do_shell") as mock_shell:
            engine._do_sequence(macro["steps"])
            assert mock_shell.call_count == 2

    def test_sequence_step_delay_applied(self, tmp_path):
        from g510.config import Config
        from g510.profiles import ProfileManager
        from g510.macros import MacroEngine

        cfg = Config(tmp_path / "c.toml")
        pm  = ProfileManager(tmp_path / "p")
        pm.load_active()

        steps = [
            {"type": "shell", "command": "true", "delay_ms": 50},
        ]
        with patch("g510.macros.UInput", MagicMock()):
            engine = MacroEngine(pm, cfg)
        engine._uinput = None

        with patch.object(engine, "_do_shell"), \
             patch("time.sleep") as mock_sleep:
            engine._do_sequence(steps)
            mock_sleep.assert_called_with(0.05)
