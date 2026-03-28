"""
g510.config — loads and validates the daemon configuration (TOML).
"""

import os
import logging
import tomllib  # Python 3.11+; use tomli for older versions
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)

DEFAULT_CONFIG = """
[daemon]
# Path where input event devices are searched
input_device_pattern = "/dev/input/by-id/*Logitech*G510*"
# hidraw device for LCD/direct USB (leave empty for auto-detect)
hidraw_device = ""

[lcd]
enabled = true
# Refresh rate in frames per second
fps = 4
# Font path for text rendering (uses system font if empty)
font_path = ""
font_size = 10
# Default screen: "clock", "sysinfo", "nowplaying", "custom"
default_screen = "clock"

[rgb]
# Control method: "sysfs" (kernel LEDs) or "usb" (direct via libg15)
method = "sysfs"
# Default color on startup (R, G, B 0-255)
default_color = [255, 128, 0]

[macros]
# Macro scripts directory
scripts_dir = "~/.config/g510/macros"
# Delay between simulated keystrokes (ms)
keystroke_delay_ms = 20

[volume]
# Volume change per wheel click (percent)
step = 5

[model]
# Force keyboard model: "auto" | "g510" | "g510s"
# Leave "auto" to detect from USB bus
model = "auto"
# Keycodes (decimal) that trigger game-mode key on G510s.
# Run: evtest /dev/input/eventN   to find the correct code for your kernel.
game_mode_keycodes = [420, 584]

[profiles]
# Directory for profile JSON files
profiles_dir = "~/.config/g510/profiles"
active_profile = "default"
"""


# Valid fps range — cap to prevent 100% CPU from misconfiguration
LCD_FPS_MIN = 1
LCD_FPS_MAX = 30

@dataclass
class LCDConfig:
    enabled: bool = True
    fps: int = 4
    font_path: str = ""
    font_size: int = 10
    default_screen: str = "clock"

    def __post_init__(self):
        self.fps = max(LCD_FPS_MIN, min(LCD_FPS_MAX, self.fps))


@dataclass
class RGBConfig:
    method: str = "sysfs"
    default_color: list = field(default_factory=lambda: [255, 128, 0])


@dataclass
class MacroConfig:
    scripts_dir: Path = Path("~/.config/g510/macros")
    keystroke_delay_ms: int = 20


class Config:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self._raw = {}
        self._load()

    def _load(self):
        if self.config_path.exists():
            with open(self.config_path, "rb") as f:
                self._raw = tomllib.load(f)
            log.debug("Loaded config: %s", self.config_path)
        else:
            log.info("No config file at %s — using defaults", self.config_path)
            self._write_defaults()

    def _write_defaults(self):
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(DEFAULT_CONFIG)
        log.info("Wrote default config to %s", self.config_path)
        import tomllib as tl
        self._raw = tl.loads(DEFAULT_CONFIG)

    def _get(self, *keys, default=None):
        d = self._raw
        for k in keys:
            if not isinstance(d, dict) or k not in d:
                return default
            d = d[k]
        return d

    @property
    def input_device_pattern(self) -> str:
        return self._get("daemon", "input_device_pattern",
                         default="/dev/input/by-id/*Logitech*G510*")

    @property
    def hidraw_device(self) -> str:
        return self._get("daemon", "hidraw_device", default="")

    @property
    def lcd(self) -> LCDConfig:
        s = self._get("lcd") or {}
        return LCDConfig(
            enabled=s.get("enabled", True),
            fps=s.get("fps", 4),
            font_path=s.get("font_path", ""),
            font_size=s.get("font_size", 10),
            default_screen=s.get("default_screen", "clock"),
        )

    @property
    def rgb(self) -> RGBConfig:
        s = self._get("rgb") or {}
        return RGBConfig(
            method=s.get("method", "sysfs"),
            default_color=s.get("default_color", [255, 128, 0]),
        )

    @property
    def macros(self) -> MacroConfig:
        s = self._get("macros") or {}
        return MacroConfig(
            scripts_dir=Path(s.get("scripts_dir", "~/.config/g510/macros")).expanduser(),
            keystroke_delay_ms=s.get("keystroke_delay_ms", 20),
        )

    @property
    def profiles_dir(self) -> Path:
        d = self._get("profiles", "profiles_dir", default="~/.config/g510/profiles")
        return Path(d).expanduser()

    @property
    def model_hint(self) -> str:
        return self._get("model", "model", default="auto")

    @property
    def game_mode_keycodes(self) -> set:
        codes = self._get("model", "game_mode_keycodes", default=[420, 584])
        return set(int(c) for c in codes)

    @property
    def active_profile(self) -> str:
        return self._get("profiles", "active_profile", default="default")
