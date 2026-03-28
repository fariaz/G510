"""
tests/conftest.py — shared pytest fixtures for the G510 test suite.
"""
import sys
import tempfile
import warnings
from pathlib import Path
from unittest.mock import MagicMock, patch

# Suppress harmless import warnings during testing
warnings.filterwarnings("ignore", message=".*evdev.*")
warnings.filterwarnings("ignore", message=".*dbus.*")
warnings.filterwarnings("ignore", message=".*Pillow.*")

# Make the daemon package importable
sys.path.insert(0, str(Path(__file__).parent.parent / "daemon"))

import pytest


@pytest.fixture
def tmp_config(tmp_path):
    """A Config object backed by a temp directory."""
    from g510.config import Config
    return Config(tmp_path / "config.toml")


@pytest.fixture
def tmp_profiles(tmp_path):
    """A ProfileManager with a loaded default profile."""
    from g510.profiles import ProfileManager
    pm = ProfileManager(tmp_path / "profiles")
    pm.load_active("default")
    return pm


@pytest.fixture
def mock_lcd():
    """A MagicMock standing in for LCDManager."""
    lcd = MagicMock()
    lcd.set_screen = MagicMock()
    lcd.notify_bank_change = MagicMock()
    return lcd


@pytest.fixture
def mock_rgb():
    """A MagicMock standing in for RGBController."""
    rgb = MagicMock()
    rgb.set_color = MagicMock()
    rgb.set_mled = MagicMock()
    rgb.apply = MagicMock()
    return rgb


@pytest.fixture
def macro_engine(tmp_config, tmp_profiles):
    """A MacroEngine with uinput disabled (safe for CI)."""
    from g510.macros import MacroEngine
    with patch("g510.macros.UInput", MagicMock()):
        engine = MacroEngine(tmp_profiles, tmp_config)
    engine._uinput = None
    return engine


@pytest.fixture
def keyboard(tmp_config, macro_engine, mock_rgb, mock_lcd, tmp_profiles):
    """A G510Keyboard with all hardware dependencies mocked."""
    from g510.keyboard import G510Keyboard
    return G510Keyboard(tmp_config, macro_engine, mock_rgb, mock_lcd, tmp_profiles)


@pytest.fixture
def lcd_manager(tmp_config):
    """A LCDManager with hidraw and font loading mocked out."""
    from g510.lcd import LCDManager
    with patch.object(LCDManager, "_find_hidraw", return_value=None), \
         patch.object(LCDManager, "_load_fonts"):
        mgr = LCDManager(tmp_config)
    return mgr


@pytest.fixture
def recorder(tmp_profiles, mock_lcd):
    """A MacroRecorder in idle state."""
    from g510.macrorec import MacroRecorder
    return MacroRecorder(tmp_profiles, mock_lcd)
