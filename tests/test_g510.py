"""
tests/test_g510.py — unit tests for the G510 daemon modules.

Run with:  pytest tests/ -v
"""

import json
import pytest
import sys
import os
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

# Add daemon dir to path
sys.path.insert(0, str(Path(__file__).parent.parent / "daemon"))


# ─── lcd_wire ─────────────────────────────────────────────────────────────────

class TestLCDWire:
    def test_encode_frame_returns_6_reports(self):
        from g510.lcd_wire import encode_frame, LCD_WIDTH, LCD_HEIGHT
        pixels = [[0] * LCD_WIDTH for _ in range(LCD_HEIGHT)]
        reports = encode_frame(pixels)
        assert len(reports) == 6

    def test_each_report_is_256_bytes(self):
        from g510.lcd_wire import encode_frame, LCD_WIDTH, LCD_HEIGHT
        pixels = [[0] * LCD_WIDTH for _ in range(LCD_HEIGHT)]
        reports = encode_frame(pixels)
        for i, r in enumerate(reports):
            assert len(r) == 256, f"Report {i} is {len(r)} bytes, expected 256"

    def test_report_id_is_0x03(self):
        from g510.lcd_wire import encode_frame, LCD_WIDTH, LCD_HEIGHT
        pixels = [[0] * LCD_WIDTH for _ in range(LCD_HEIGHT)]
        reports = encode_frame(pixels)
        for i, r in enumerate(reports):
            assert r[0] == 0x03, f"Report {i}: expected ID 0x03, got {r[0]:#04x}"

    def test_page_index_increments(self):
        from g510.lcd_wire import encode_frame, LCD_WIDTH, LCD_HEIGHT
        pixels = [[0] * LCD_WIDTH for _ in range(LCD_HEIGHT)]
        reports = encode_frame(pixels)
        for i, r in enumerate(reports):
            assert r[2] == i, f"Report {i} has page index {r[2]}, expected {i}"

    def test_all_black_pixels_all_bits_set(self):
        """All black (lit) pixels should produce 0x7F in each column byte."""
        from g510.lcd_wire import encode_frame, LCD_WIDTH, LCD_HEIGHT
        # All pixels = 1 (lit)
        pixels = [[1] * LCD_WIDTH for _ in range(LCD_HEIGHT)]
        reports = encode_frame(pixels)
        # For pages 0–4 (full 7 rows): each col byte = 0x7F (bits 0–6 set)
        for page in range(5):
            r = reports[page]
            for col in range(LCD_WIDTH):
                assert r[4 + col] == 0x7F, (
                    f"Page {page} col {col}: expected 0x7F, got {r[4+col]:#04x}"
                )

    def test_all_white_pixels_all_bits_clear(self):
        """All white (unlit) pixels should produce 0x00."""
        from g510.lcd_wire import encode_frame, LCD_WIDTH, LCD_HEIGHT
        pixels = [[0] * LCD_WIDTH for _ in range(LCD_HEIGHT)]
        reports = encode_frame(pixels)
        for page in range(6):
            r = reports[page]
            for col in range(LCD_WIDTH):
                assert r[4 + col] == 0x00, (
                    f"Page {page} col {col}: expected 0x00, got {r[4+col]:#04x}"
                )

    def test_single_pixel_top_left(self):
        """Pixel at (col=0, row=0) should set bit 0 of page 0, col 0."""
        from g510.lcd_wire import encode_frame, LCD_WIDTH, LCD_HEIGHT
        pixels = [[0] * LCD_WIDTH for _ in range(LCD_HEIGHT)]
        pixels[0][0] = 1  # row=0, col=0
        reports = encode_frame(pixels)
        assert reports[0][4] & 0x01, "Bit 0 of page 0 col 0 should be set"
        # All other bytes in this page col should be 0
        for col in range(1, LCD_WIDTH):
            assert reports[0][4 + col] == 0

    def test_frame_from_pil(self):
        """PIL Image path should produce 6 reports."""
        from g510.lcd_wire import frame_from_pil
        try:
            from PIL import Image
        except ImportError:
            pytest.skip("Pillow not installed")
        img = Image.new("1", (160, 43), 0)
        reports = frame_from_pil(img)
        assert len(reports) == 6
        for r in reports:
            assert len(r) == 256


# ─── profiles ─────────────────────────────────────────────────────────────────

class TestProfiles:
    def test_profile_get_macro_returns_none_when_unbound(self):
        from g510.profiles import Profile
        p = Profile({"name": "test", "macros": {"M1": {}}})
        assert p.get_macro("G1", "M1") is None

    def test_profile_get_macro_returns_action(self):
        from g510.profiles import Profile
        action = {"type": "shell", "command": "xterm"}
        p = Profile({"name": "test", "macros": {"M1": {"G1": action}}})
        assert p.get_macro("G1", "M1") == action

    def test_profile_set_macro(self):
        from g510.profiles import Profile
        p = Profile({"name": "test", "macros": {}})
        action = {"type": "keystroke", "keys": "ctrl+c"}
        p.set_macro("G2", "M2", action)
        assert p.get_macro("G2", "M2") == action

    def test_profile_delete_macro(self):
        from g510.profiles import Profile
        action = {"type": "shell", "command": "ls"}
        p = Profile({"name": "test", "macros": {"M1": {"G1": action}}})
        p.delete_macro("G1", "M1")
        assert p.get_macro("G1", "M1") is None

    def test_profile_set_rgb(self):
        from g510.profiles import Profile
        p = Profile({"name": "test"})
        p.set_rgb(100, 200, 50)
        assert p.rgb["color"] == [100, 200, 50]

    def test_profile_to_dict(self):
        from g510.profiles import Profile
        data = {"name": "x", "macros": {}, "rgb": {"color": [1, 2, 3]}}
        p = Profile(data)
        assert p.to_dict() == data

    def test_profile_manager_load_creates_default(self, tmp_path):
        from g510.profiles import ProfileManager
        pm = ProfileManager(tmp_path)
        pm.load_active("default")
        assert (tmp_path / "default.json").exists()
        assert pm.active.name == "default"

    def test_profile_manager_list(self, tmp_path):
        from g510.profiles import ProfileManager
        pm = ProfileManager(tmp_path)
        pm.load_active("default")
        pm.create_profile("gaming")
        profiles = pm.list_profiles()
        assert "default" in profiles
        assert "gaming" in profiles

    def test_profile_manager_switch(self, tmp_path):
        from g510.profiles import ProfileManager
        pm = ProfileManager(tmp_path)
        pm.load_active("default")
        pm.create_profile("gaming")
        pm.switch_profile("gaming")
        assert pm.active.name == "gaming"

    def test_profile_manager_save_active(self, tmp_path):
        from g510.profiles import ProfileManager
        pm = ProfileManager(tmp_path)
        pm.load_active("default")
        pm.active.set_rgb(10, 20, 30)
        pm.save_active()
        # Reload and verify
        pm2 = ProfileManager(tmp_path)
        pm2.load_active("default")
        assert pm2.active.rgb["color"] == [10, 20, 30]

    def test_profile_manager_delete(self, tmp_path):
        from g510.profiles import ProfileManager
        pm = ProfileManager(tmp_path)
        pm.load_active("default")
        pm.create_profile("temp")
        pm.delete_profile("temp")
        assert "temp" not in pm.list_profiles()

    def test_profile_manager_cannot_delete_default(self, tmp_path):
        from g510.profiles import ProfileManager
        pm = ProfileManager(tmp_path)
        pm.load_active()
        with pytest.raises(ValueError):
            pm.delete_profile("default")


# ─── config ───────────────────────────────────────────────────────────────────

class TestConfig:
    def test_config_creates_default_file(self, tmp_path):
        from g510.config import Config
        cfg_path = tmp_path / "config.toml"
        cfg = Config(cfg_path)
        assert cfg_path.exists()

    def test_config_defaults(self, tmp_path):
        from g510.config import Config
        cfg = Config(tmp_path / "config.toml")
        assert cfg.rgb.method == "sysfs"
        assert cfg.rgb.default_color == [255, 128, 0]
        assert cfg.lcd.fps == 4
        assert cfg.lcd.default_screen == "clock"
        assert cfg.macros.keystroke_delay_ms == 20

    def test_config_custom_values(self, tmp_path):
        from g510.config import Config
        cfg_file = tmp_path / "config.toml"
        cfg_file.write_text("""
[rgb]
method = "usb"
default_color = [0, 0, 255]

[lcd]
fps = 10
default_screen = "sysinfo"
""")
        cfg = Config(cfg_file)
        assert cfg.rgb.method == "usb"
        assert cfg.rgb.default_color == [0, 0, 255]
        assert cfg.lcd.fps == 10
        assert cfg.lcd.default_screen == "sysinfo"


# ─── rgb ─────────────────────────────────────────────────────────────────────

class TestRGBController:
    def test_clamps_values(self, tmp_path):
        """Values outside 0–255 must be clamped."""
        from g510.config import Config
        from g510.rgb import RGBController
        cfg = Config(tmp_path / "config.toml")

        with patch("g510.rgb.SysfsBrightness") as MockSysfs, \
             patch("g510.rgb.USBDirectControl"):
            mock_sysfs = MagicMock()
            mock_sysfs.available.return_value = True
            MockSysfs.return_value = mock_sysfs
            rgb = RGBController(cfg)
            rgb.set_color(-10, 300, 128)
            mock_sysfs.set_color.assert_called_with(0, 255, 128)

    def test_uses_sysfs_when_available(self, tmp_path):
        from g510.config import Config
        from g510.rgb import RGBController
        cfg = Config(tmp_path / "config.toml")

        with patch("g510.rgb.SysfsBrightness") as MockSysfs, \
             patch("g510.rgb.USBDirectControl") as MockUSB:
            mock_sysfs = MagicMock()
            mock_sysfs.available.return_value = True
            MockSysfs.return_value = mock_sysfs
            rgb = RGBController(cfg)
            assert rgb._backend is mock_sysfs


# ─── macros ───────────────────────────────────────────────────────────────────

class TestMacroEngine:
    def _make_engine(self, tmp_path):
        from g510.config import Config
        from g510.profiles import ProfileManager
        from g510.macros import MacroEngine
        cfg = Config(tmp_path / "config.toml")
        pm = ProfileManager(tmp_path / "profiles")
        pm.load_active()
        with patch("g510.macros.UInput"):
            engine = MacroEngine(pm, cfg)
        engine._uinput = None  # disable uinput for tests
        return engine, pm

    def test_execute_missing_macro_is_noop(self, tmp_path):
        engine, _ = self._make_engine(tmp_path)
        # Should not raise
        engine.execute("G18", "M3")

    def test_execute_shell_macro(self, tmp_path):
        engine, pm = self._make_engine(tmp_path)
        pm.active.set_macro("G1", "M1", {"type": "shell", "command": "true"})
        with patch("subprocess.Popen") as mock_popen:
            engine._do_shell("true")
            mock_popen.assert_called_once()

    def test_execute_type_text_uses_xdotool(self, tmp_path):
        engine, _ = self._make_engine(tmp_path)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            engine._do_type_text("hello")
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert "xdotool" in args
            assert "hello" in args

    def test_execute_script_not_found(self, tmp_path, caplog):
        engine, _ = self._make_engine(tmp_path)
        import logging
        with caplog.at_level(logging.WARNING):
            engine._do_script("nonexistent.sh")
        assert "not found" in caplog.text


# ─── keyboard (light, no hardware) ───────────────────────────────────────────

class TestG510Keyboard:
    def test_init_no_devices(self, tmp_path):
        from g510.config import Config
        from g510.keyboard import G510Keyboard
        cfg = Config(tmp_path / "config.toml")
        kb = G510Keyboard(cfg,
                          macro_engine=MagicMock(),
                          rgb=MagicMock(),
                          lcd=MagicMock(),
                          profiles=MagicMock())
        # _find_devices returns empty list without hardware
        with patch("glob.glob", return_value=[]):
            devices = kb._find_devices()
        assert devices == []

    def test_bank_switch(self, tmp_path):
        from g510.config import Config
        from g510.keyboard import G510Keyboard
        cfg = Config(tmp_path / "config.toml")
        rgb = MagicMock()
        lcd = MagicMock()
        kb = G510Keyboard(cfg, macro_engine=MagicMock(), rgb=rgb, lcd=lcd, profiles=MagicMock())
        kb._switch_bank("M2")
        assert kb._current_mbank == "M2"
        rgb.set_mled.assert_called_with("M2")
        lcd.notify_bank_change.assert_called_with("M2")

    def test_bank_switch_MR_does_not_change_bank(self, tmp_path):
        from g510.config import Config
        from g510.keyboard import G510Keyboard
        cfg = Config(tmp_path / "config.toml")
        kb = G510Keyboard(cfg, macro_engine=MagicMock(), rgb=MagicMock(),
                          lcd=MagicMock(), profiles=MagicMock())
        kb._current_mbank = "M1"
        kb._switch_bank("MR")
        assert kb._current_mbank == "M1"  # MR doesn't change bank
