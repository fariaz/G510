"""
tests/test_new_features.py — tests for volume wheel, bank flash, NowPlaying,
hotplug reconnect, CPU delta tracking, and lcd_wire edge cases.

Run with:  pytest tests/ -v
"""

import sys
import time
import threading
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, str(Path(__file__).parent.parent / "daemon"))


# ─── SysInfoScreen CPU delta tracking ────────────────────────────────────────

class TestSysInfoCPU:
    def _make_screen(self):
        from g510.lcd import SysInfoScreen
        return SysInfoScreen(font_small=None)

    def test_first_call_returns_zero_or_near_zero(self):
        s = self._make_screen()
        # First call: prev_total=0, prev_idle=0
        # Any real /proc/stat values will produce ~100% on first call with old code
        # With delta tracking, result relative to (0,0) baseline is unreliable
        # but must not raise
        result = s._cpu_percent()
        assert isinstance(result, float)
        assert 0.0 <= result <= 100.0

    def test_stable_idle_gives_zero_cpu(self):
        s = self._make_screen()
        # Simulate two identical /proc/stat reads (nothing changed = 0% CPU)
        stat_line = "cpu  100 0 0 900 0 0 0"  # 900 idle out of 1000 total
        with patch("builtins.open", MagicMock(return_value=MagicMock(
            __enter__=lambda self_: self_,
            __exit__=lambda *a: None,
            readline=MagicMock(return_value=stat_line)
        ))):
            s._cpu_percent()   # prime
        with patch("builtins.open", MagicMock(return_value=MagicMock(
            __enter__=lambda self_: self_,
            __exit__=lambda *a: None,
            readline=MagicMock(return_value=stat_line)  # same values = 0 delta
        ))):
            result = s._cpu_percent()
        assert result == 0.0

    def test_full_load_gives_100_cpu(self):
        s = self._make_screen()
        idle_stat  = "cpu  0 0 0 1000 0 0 0"   # all idle
        busy_stat  = "cpu  1000 0 0 1000 0 0 0" # doubled total, same idle
        # After prime with idle, then busy reading: delta_total=1000, delta_idle=0
        with patch("builtins.open", MagicMock(return_value=MagicMock(
            __enter__=lambda self_: self_,
            __exit__=lambda *a: None,
            readline=MagicMock(return_value=idle_stat)
        ))):
            s._cpu_percent()
        with patch("builtins.open", MagicMock(return_value=MagicMock(
            __enter__=lambda self_: self_,
            __exit__=lambda *a: None,
            readline=MagicMock(return_value=busy_stat)
        ))):
            result = s._cpu_percent()
        assert result == 100.0

    def test_half_load(self):
        s = self._make_screen()
        stat1 = "cpu  0 0 0 500 0 0 0"
        stat2 = "cpu  500 0 0 500 0 0 0"  # 500 new busy, 0 new idle → 50%
        for stat in [stat1, stat2]:
            with patch("builtins.open", MagicMock(return_value=MagicMock(
                __enter__=lambda self_: self_,
                __exit__=lambda *a: None,
                readline=MagicMock(return_value=stat)
            ))):
                result = s._cpu_percent()
        assert abs(result - 50.0) < 0.1


# ─── BankFlashScreen ─────────────────────────────────────────────────────────

class TestBankFlashScreen:
    def test_not_expired_immediately(self):
        from g510.lcd import BankFlashScreen
        flash = BankFlashScreen("M2", font=None)
        assert not flash.expired()

    def test_expired_after_ttl(self):
        from g510.lcd import BankFlashScreen
        flash = BankFlashScreen("M3", font=None)
        flash.ttl = 0.05
        time.sleep(0.1)
        assert flash.expired()

    def test_render_returns_image(self):
        from g510.lcd import BankFlashScreen
        try:
            from PIL import Image
        except ImportError:
            return
        flash = BankFlashScreen("M1", font=None)
        img = flash.render()
        assert img.size == (160, 43)

    def test_bank_label_in_render(self):
        """Bank name should be somewhere in the rendered pixels (not all white)."""
        from g510.lcd import BankFlashScreen
        try:
            from PIL import Image
        except ImportError:
            return
        flash = BankFlashScreen("M2", font=None)
        img = flash.render()
        pixels = list(img.getdata())
        # Should have some black pixels (the "M2" text)
        assert any(p == 0 for p in pixels), "BankFlash render should contain dark pixels"


# ─── LCDManager notify_bank_change ───────────────────────────────────────────

class TestLCDManagerBankFlash:
    def _make_manager(self, tmp_path):
        from g510.config import Config
        from g510.lcd import LCDManager
        cfg = Config(tmp_path / "config.toml")
        with patch.object(LCDManager, "_find_hidraw", return_value=None), \
             patch.object(LCDManager, "_load_fonts"):
            mgr = LCDManager(cfg)
        return mgr

    def test_notify_bank_change_switches_screen(self, tmp_path):
        from g510.lcd import BankFlashScreen
        mgr = self._make_manager(tmp_path)
        orig = mgr._screen
        mgr.notify_bank_change("M3")
        with mgr._lock:
            assert isinstance(mgr._screen, BankFlashScreen)
            assert mgr._screen.bank == "M3"

    def test_notify_bank_change_restores_screen(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        orig = mgr._screen
        mgr.notify_bank_change("M2")
        # Find the flash screen and force-expire it
        with mgr._lock:
            flash = mgr._screen
            flash.ttl = 0.05
        time.sleep(0.2)   # wait for restore thread
        with mgr._lock:
            assert mgr._screen is orig

    def test_manual_change_prevents_restore(self, tmp_path):
        """If the user changes screen during flash, the restore should not clobber it."""
        from g510.lcd import ClockScreen
        mgr = self._make_manager(tmp_path)
        mgr.notify_bank_change("M1")
        # Immediately switch to something else
        new_screen = ClockScreen()
        with mgr._lock:
            mgr._screen = new_screen
        time.sleep(0.2)
        with mgr._lock:
            # Should still be the screen we manually set
            assert mgr._screen is new_screen


# ─── NowPlayingScreen ────────────────────────────────────────────────────────

class TestNowPlayingScreen:
    def test_no_player_shows_nothing_playing(self):
        from g510.lcd import NowPlayingScreen
        try:
            from PIL import Image
        except ImportError:
            return
        screen = NowPlayingScreen()
        with patch.object(NowPlayingScreen, "_poll_playerctl", return_value=("", "", 0.0)):
            img = screen.render()
        assert img.size == (160, 43)

    def test_with_player_returns_image(self):
        from g510.lcd import NowPlayingScreen
        try:
            from PIL import Image
        except ImportError:
            return
        screen = NowPlayingScreen()
        with patch.object(NowPlayingScreen, "_poll_playerctl",
                          return_value=("Artist Name", "Song Title", 0.4)):
            img = screen.render()
        assert img.size == (160, 43)

    def test_cache_avoids_repeated_calls(self):
        from g510.lcd import NowPlayingScreen
        screen = NowPlayingScreen()
        screen._UPDATE_INTERVAL = 999   # effectively infinite
        screen._last_update = time.monotonic()
        screen._cache = ("Cached Artist", "Cached Title", 0.5)

        call_count = {"n": 0}
        def mock_poll():
            call_count["n"] += 1
            return ("New", "New", 0.0)

        with patch.object(NowPlayingScreen, "_poll_playerctl", side_effect=mock_poll):
            try:
                from PIL import Image
                screen.render()
                screen.render()
            except Exception:
                pass
        assert call_count["n"] == 0, "Should use cache, not re-poll"

    def test_poll_playerctl_no_player(self):
        from g510.lcd import NowPlayingScreen
        with patch("subprocess.check_output", side_effect=Exception("no player")):
            result = NowPlayingScreen._poll_playerctl()
        assert result == ("", "", 0.0)

    def test_poll_playerctl_playing(self):
        from g510.lcd import NowPlayingScreen
        responses = {
            ("playerctl", "status"):              b"Playing\n",
            ("playerctl", "metadata", "artist"):  b"Daft Punk\n",
            ("playerctl", "metadata", "title"):   b"Around the World\n",
            ("playerctl", "metadata", "mpris:length"): b"224000000\n",  # 224s in µs
            ("playerctl", "position"):             b"112.0\n",          # 50%
        }
        def fake_check_output(args, **kwargs):
            key = tuple(args)
            return responses.get(key, b"\n")

        with patch("subprocess.check_output", side_effect=fake_check_output):
            artist, title, pos = NowPlayingScreen._poll_playerctl()

        assert artist == "Daft Punk"
        assert title == "Around the World"
        assert abs(pos - 0.5) < 0.01


# ─── Volume wheel ─────────────────────────────────────────────────────────────

class TestVolumeWheel:
    def _make_keyboard(self, tmp_path):
        from g510.config import Config
        from g510.keyboard import G510Keyboard
        cfg = Config(tmp_path / "config.toml")
        return G510Keyboard(cfg,
                            macro_engine=MagicMock(),
                            rgb=MagicMock(),
                            lcd=MagicMock(),
                            profiles=MagicMock())

    def test_wheel_up_increases_volume(self, tmp_path):
        kb = self._make_keyboard(tmp_path)
        with patch("subprocess.Popen") as mock_popen:
            kb._handle_volume_wheel(1)
            args = mock_popen.call_args[0][0]
            assert "pactl" in args
            assert any("+" in a for a in args), f"Expected + in args: {args}"

    def test_wheel_down_decreases_volume(self, tmp_path):
        kb = self._make_keyboard(tmp_path)
        with patch("subprocess.Popen") as mock_popen:
            kb._handle_volume_wheel(-1)
            args = mock_popen.call_args[0][0]
            assert "pactl" in args
            assert any("-" in a for a in args), f"Expected - in args: {args}"

    def test_wheel_missing_pactl_no_crash(self, tmp_path):
        kb = self._make_keyboard(tmp_path)
        with patch("subprocess.Popen", side_effect=FileNotFoundError):
            kb._handle_volume_wheel(1)   # must not raise


# ─── Hotplug reconnect ────────────────────────────────────────────────────────

class TestHotplug:
    def _make_keyboard(self, tmp_path):
        from g510.config import Config
        from g510.keyboard import G510Keyboard
        cfg = Config(tmp_path / "config.toml")
        return G510Keyboard(cfg,
                            macro_engine=MagicMock(),
                            rgb=MagicMock(),
                            lcd=MagicMock(),
                            profiles=MagicMock())

    def test_reconnect_loop_picks_up_new_device(self, tmp_path):
        kb = self._make_keyboard(tmp_path)
        kb._running = True
        kb._reconnect_interval = 0.05

        fake_dev = MagicMock()
        fake_dev.path = "/dev/input/event99"

        with patch.object(kb, "_find_devices", return_value=[fake_dev]), \
             patch.object(kb, "_start_device_thread") as mock_start:
            t = threading.Thread(target=kb._reconnect_loop, daemon=True)
            t.start()
            time.sleep(0.15)
            kb._running = False
            t.join(timeout=0.5)

        mock_start.assert_called_with(fake_dev)

    def test_reconnect_skips_known_device(self, tmp_path):
        kb = self._make_keyboard(tmp_path)
        kb._running = True
        kb._reconnect_interval = 0.05

        fake_dev = MagicMock()
        fake_dev.path = "/dev/input/event99"
        kb._devices = [fake_dev]   # already known

        new_candidate = MagicMock()
        new_candidate.path = "/dev/input/event99"  # same path

        with patch.object(kb, "_find_devices", return_value=[new_candidate]), \
             patch.object(kb, "_start_device_thread") as mock_start:
            t = threading.Thread(target=kb._reconnect_loop, daemon=True)
            t.start()
            time.sleep(0.15)
            kb._running = False
            t.join(timeout=0.5)

        mock_start.assert_not_called()


# ─── lcd_wire edge cases ──────────────────────────────────────────────────────

class TestLCDWireEdgeCases:
    def test_last_page_only_uses_one_row(self):
        """Page 5 (index 5) only has 1 pixel row (row 42), bits 1–6 unused."""
        from g510.lcd_wire import encode_frame, LCD_WIDTH, LCD_HEIGHT
        pixels = [[0] * LCD_WIDTH for _ in range(LCD_HEIGHT)]
        # Set only row 42 (the single row in page 5)
        for col in range(LCD_WIDTH):
            pixels[42][col] = 1
        reports = encode_frame(pixels)
        page5 = reports[5]
        for col in range(LCD_WIDTH):
            byte = page5[4 + col]
            # Bit 0 should be set (row 42 = page 5 row 0)
            assert byte & 0x01, f"Col {col}: bit 0 should be set"
            # Bits 1–6 should be clear (no more rows in last page)
            assert (byte & 0x7E) == 0, f"Col {col}: bits 1-6 should be clear, got {byte:#010b}"

    def test_pixel_at_row_42_col_159(self):
        """Bottom-right pixel is in page 5, column 159, bit 0."""
        from g510.lcd_wire import encode_frame, LCD_WIDTH, LCD_HEIGHT
        pixels = [[0] * LCD_WIDTH for _ in range(LCD_HEIGHT)]
        pixels[42][159] = 1
        reports = encode_frame(pixels)
        assert reports[5][4 + 159] & 0x01
        # All other column bytes in page 5 should be 0
        for col in range(159):
            assert reports[5][4 + col] == 0

    def test_all_pages_have_correct_byte_at_index_1(self):
        """Byte 1 of every report should be 0x00."""
        from g510.lcd_wire import encode_frame, LCD_WIDTH, LCD_HEIGHT
        pixels = [[0] * LCD_WIDTH for _ in range(LCD_HEIGHT)]
        reports = encode_frame(pixels)
        for i, r in enumerate(reports):
            assert r[1] == 0x00, f"Report {i} byte[1] = {r[1]:#04x}, expected 0x00"

    def test_send_frame_writes_all_reports(self, tmp_path):
        from g510.lcd_wire import send_frame
        hidraw = tmp_path / "fake_hidraw"
        reports = [bytes(256)] * 6
        result = send_frame(str(hidraw), reports)
        assert result
        data = hidraw.read_bytes()
        assert len(data) == 256 * 6

    def test_send_frame_returns_false_on_error(self, tmp_path):
        from g510.lcd_wire import send_frame
        result = send_frame("/dev/null/nonexistent", [bytes(256)] * 6)
        assert result is False
