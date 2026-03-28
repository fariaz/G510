"""
tests/test_g510s.py — tests for G510s-specific features.

Covers: model detection, capabilities, mute LED tracking,
        game-mode key, PID recognition, config hint override.
"""

import sys
import warnings
from pathlib import Path
from unittest.mock import MagicMock, patch, call

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent.parent / "daemon"))

import pytest
from g510.model import (
    KeyboardModel, Capabilities, PID,
    detect_model, model_name, _find_pid_lsusb, _find_pid_sysfs,
)


# ─── PID classification ───────────────────────────────────────────────────────

class TestPIDSets:
    def test_g510_pids_in_all(self):
        assert PID.G510_KBD   in PID.ALL_KBD
        assert PID.G510_AUDIO in PID.ALL_KBD

    def test_g510s_pids_in_all(self):
        assert PID.G510S_KBD   in PID.ALL_KBD
        assert PID.G510S_AUDIO in PID.ALL_KBD

    def test_g510_set_correct(self):
        assert PID.G510_KBD   in PID.G510_ALL
        assert PID.G510_AUDIO in PID.G510_ALL
        assert PID.G510S_KBD  not in PID.G510_ALL

    def test_g510s_set_correct(self):
        assert PID.G510S_KBD   in PID.G510S_ALL
        assert PID.G510S_AUDIO in PID.G510S_ALL
        assert PID.G510_KBD    not in PID.G510S_ALL

    def test_audio_pids(self):
        assert PID.G510_AUDIO  in PID.AUDIO_PIDS
        assert PID.G510S_AUDIO in PID.AUDIO_PIDS
        assert PID.G510_KBD    not in PID.AUDIO_PIDS
        assert PID.G510S_KBD   not in PID.AUDIO_PIDS

    def test_pid_str(self):
        assert PID.pid_str(PID.G510_KBD)    == "c22d"
        assert PID.pid_str(PID.G510_AUDIO)  == "c22e"
        assert PID.pid_str(PID.G510S_KBD)   == "c24d"
        assert PID.pid_str(PID.G510S_AUDIO) == "c24e"


# ─── Capabilities ─────────────────────────────────────────────────────────────

class TestCapabilities:
    def test_g510_capabilities(self):
        caps = Capabilities(KeyboardModel.G510)
        assert caps.gkeys
        assert caps.mkeys
        assert caps.media_keys
        assert caps.rgb
        assert caps.lcd
        assert not caps.headphone_mute_led
        assert not caps.mic_mute_led
        assert not caps.game_mode_key

    def test_g510s_capabilities(self):
        caps = Capabilities(KeyboardModel.G510S)
        assert caps.gkeys
        assert caps.mkeys
        assert caps.media_keys
        assert caps.rgb
        assert caps.lcd
        assert caps.headphone_mute_led   # G510s only
        assert caps.mic_mute_led         # G510s only
        assert caps.game_mode_key        # G510s only

    def test_audio_active_flag(self):
        caps = Capabilities(KeyboardModel.G510S, audio_active=True)
        assert caps.audio_active

    def test_unknown_model_no_extras(self):
        caps = Capabilities(KeyboardModel.UNKNOWN)
        assert not caps.headphone_mute_led
        assert not caps.mic_mute_led
        assert not caps.game_mode_key

    def test_repr_g510(self):
        caps = Capabilities(KeyboardModel.G510)
        assert "G510" in repr(caps)
        assert "hp-mute-led" not in repr(caps)

    def test_repr_g510s(self):
        caps = Capabilities(KeyboardModel.G510S)
        assert "G510S" in repr(caps)
        assert "hp-mute-led" in repr(caps)
        assert "mic-mute-led" in repr(caps)
        assert "game-mode-key" in repr(caps)


# ─── Model detection — config hint override ───────────────────────────────────

class TestDetectModelHint:
    def test_hint_g510_overrides_detection(self):
        with patch("g510.model._audio_active", return_value=False):
            model, caps = detect_model("g510")
        assert model == KeyboardModel.G510
        assert not caps.game_mode_key

    def test_hint_g510s_overrides_detection(self):
        with patch("g510.model._audio_active", return_value=False):
            model, caps = detect_model("g510s")
        assert model == KeyboardModel.G510S
        assert caps.game_mode_key
        assert caps.headphone_mute_led

    def test_hint_case_insensitive(self):
        with patch("g510.model._audio_active", return_value=False):
            model, _ = detect_model("G510S")
        assert model == KeyboardModel.G510S

    def test_hint_auto_calls_usb_detect(self):
        with patch("g510.model._detect_from_usb", return_value=KeyboardModel.G510S) as mock_d, \
             patch("g510.model._audio_active", return_value=False):
            model, _ = detect_model("auto")
        mock_d.assert_called_once()
        assert model == KeyboardModel.G510S


# ─── Model detection — lsusb parsing ─────────────────────────────────────────

class TestLsusbDetection:
    def _lsusb_output(self, pid_hex: str) -> str:
        return (
            f"Bus 001 Device 002: ID 046d:{pid_hex} Logitech, Inc. G510 Gaming Keyboard\n"
            f"Bus 001 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub\n"
        )

    def test_detects_g510_kbd_pid(self):
        with patch("subprocess.check_output",
                   return_value=self._lsusb_output("c22d").encode()):
            pid = _find_pid_lsusb()
        assert pid == PID.G510_KBD

    def test_detects_g510_audio_pid(self):
        with patch("subprocess.check_output",
                   return_value=self._lsusb_output("c22e").encode()):
            pid = _find_pid_lsusb()
        assert pid == PID.G510_AUDIO

    def test_detects_g510s_kbd_pid(self):
        with patch("subprocess.check_output",
                   return_value=self._lsusb_output("c24d").encode()):
            pid = _find_pid_lsusb()
        assert pid == PID.G510S_KBD

    def test_detects_g510s_audio_pid(self):
        with patch("subprocess.check_output",
                   return_value=self._lsusb_output("c24e").encode()):
            pid = _find_pid_lsusb()
        assert pid == PID.G510S_AUDIO

    def test_returns_none_when_lsusb_not_found(self):
        with patch("subprocess.check_output", side_effect=FileNotFoundError):
            pid = _find_pid_lsusb()
        assert pid is None

    def test_returns_none_when_no_g510_on_bus(self):
        with patch("subprocess.check_output",
                   return_value=b"Bus 001 Device 001: ID 1d6b:0002 Linux Foundation\n"):
            pid = _find_pid_lsusb()
        assert pid is None

    def test_g510_model_from_lsusb(self):
        with patch("subprocess.check_output",
                   return_value=self._lsusb_output("c22d").encode()), \
             patch("g510.model._audio_active", return_value=False):
            model, caps = detect_model("auto")
        assert model == KeyboardModel.G510
        assert not caps.game_mode_key

    def test_g510s_model_from_lsusb(self):
        with patch("subprocess.check_output",
                   return_value=self._lsusb_output("c24d").encode()), \
             patch("g510.model._audio_active", return_value=False):
            model, caps = detect_model("auto")
        assert model == KeyboardModel.G510S
        assert caps.game_mode_key


# ─── RGB mute LEDs ────────────────────────────────────────────────────────────

class TestRGBMuteLEDs:
    def _make_usb_backend(self):
        from g510.rgb import USBDirectControl
        backend = USBDirectControl.__new__(USBDirectControl)
        backend._dev    = MagicMock()
        backend._iface  = 1
        backend._usb_util = MagicMock()
        backend._ctrl   = MagicMock(return_value=True)
        return backend

    def test_set_headphone_mute_led_on(self):
        from g510.rgb import HP_MUTE_BIT, REPORT_MLED
        b = self._make_usb_backend()
        b.set_headphone_mute_led(True)
        b._ctrl.assert_called_once_with(REPORT_MLED, bytes([HP_MUTE_BIT, 0, 0, 0]))

    def test_set_headphone_mute_led_off(self):
        from g510.rgb import REPORT_MLED
        b = self._make_usb_backend()
        b.set_headphone_mute_led(False)
        b._ctrl.assert_called_once_with(REPORT_MLED, bytes([0, 0, 0, 0]))

    def test_set_mic_mute_led_on(self):
        from g510.rgb import MIC_MUTE_BIT, REPORT_MLED
        b = self._make_usb_backend()
        b.set_mic_mute_led(True)
        b._ctrl.assert_called_once_with(REPORT_MLED, bytes([MIC_MUTE_BIT, 0, 0, 0]))

    def test_set_mic_mute_led_off(self):
        from g510.rgb import REPORT_MLED
        b = self._make_usb_backend()
        b.set_mic_mute_led(False)
        b._ctrl.assert_called_once_with(REPORT_MLED, bytes([0, 0, 0, 0]))

    def test_rgb_controller_delegates_hp_led(self):
        import tempfile
        from g510.config import Config
        from g510.rgb import RGBController, USBDirectControl
        with tempfile.TemporaryDirectory() as td:
            cfg = Config(Path(td) / "c.toml")
            with patch("g510.rgb.SysfsBrightness") as MockSysfs, \
                 patch("g510.rgb.USBDirectControl") as MockUSB:
                mock_usb = MagicMock(spec=USBDirectControl)
                mock_usb.available.return_value = True
                MockUSB.return_value = mock_usb
                MockSysfs.return_value = MagicMock(available=MagicMock(return_value=False))
                rgb = RGBController(cfg)
                rgb.set_headphone_mute_led(True)
                mock_usb.set_headphone_mute_led.assert_called_once_with(True)

    def test_rgb_controller_noop_on_sysfs_backend(self):
        """set_headphone_mute_led is silently ignored on sysfs backend."""
        import tempfile
        from g510.config import Config
        from g510.rgb import RGBController
        with tempfile.TemporaryDirectory() as td:
            cfg = Config(Path(td) / "c.toml")
            with patch("g510.rgb.SysfsBrightness") as MockSysfs, \
                 patch("g510.rgb.USBDirectControl"):
                mock_sysfs = MagicMock()
                mock_sysfs.available.return_value = True
                MockSysfs.return_value = mock_sysfs
                rgb = RGBController(cfg)
                rgb.set_headphone_mute_led(True)   # must not raise
                rgb.set_mic_mute_led(False)          # must not raise


# ─── Game mode (G510s) ────────────────────────────────────────────────────────

class TestGameMode:
    def _make_keyboard(self, tmp_path, model=KeyboardModel.G510S):
        from g510.config import Config
        from g510.keyboard import G510Keyboard
        from g510.model import Capabilities
        cfg = Config(tmp_path / "c.toml")
        pm  = MagicMock()
        kb  = G510Keyboard(cfg, MagicMock(), MagicMock(), MagicMock(), pm)
        kb._model = model
        kb._caps  = Capabilities(model)
        return kb

    def test_game_mode_starts_off(self, tmp_path):
        kb = self._make_keyboard(tmp_path)
        assert not kb._game_mode

    def test_game_mode_toggles_on_key_press(self, tmp_path):
        kb = self._make_keyboard(tmp_path)
        kb._handle_game_mode_key(pressed=True)
        assert kb._game_mode

    def test_game_mode_toggles_off_on_second_press(self, tmp_path):
        kb = self._make_keyboard(tmp_path)
        kb._handle_game_mode_key(pressed=True)
        kb._handle_game_mode_key(pressed=True)
        assert not kb._game_mode

    def test_game_mode_key_release_is_noop(self, tmp_path):
        kb = self._make_keyboard(tmp_path)
        kb._handle_game_mode_key(pressed=False)
        assert not kb._game_mode

    def test_game_mode_notifies_lcd(self, tmp_path):
        kb = self._make_keyboard(tmp_path)
        kb._handle_game_mode_key(pressed=True)
        kb.lcd.set_screen.assert_called()

    def test_game_mode_on_g510_still_works(self, tmp_path):
        """Non-G510s keyboards can still toggle game mode if key fires."""
        kb = self._make_keyboard(tmp_path, model=KeyboardModel.G510)
        kb._handle_game_mode_key(pressed=True)
        assert kb._game_mode


# ─── model_name helper ────────────────────────────────────────────────────────

class TestModelName:
    def test_g510_name(self):
        assert "G510" in model_name(KeyboardModel.G510)
        assert "G510s" not in model_name(KeyboardModel.G510)

    def test_g510s_name(self):
        assert "G510s" in model_name(KeyboardModel.G510S)

    def test_unknown_name(self):
        assert model_name(KeyboardModel.UNKNOWN)  # just doesn't raise
