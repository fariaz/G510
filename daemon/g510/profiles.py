"""
g510.profiles — load/save macro + color profiles (JSON).

Profile structure:
{
  "name": "default",
  "rgb": { "color": [255, 128, 0] },
  "lcd": { "screen": "clock" },
  "macros": {
    "M1": {
      "G1": { "type": "shell", "command": "xterm" },
      "G2": { "type": "keystroke", "keys": "ctrl+c" },
      "G3": { "type": "text", "text": "hello world" }
    },
    "M2": { ... },
    "M3": { ... }
  }
}
"""

import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

DEFAULT_PROFILE = {
    "name": "default",
    "rgb": {"color": [255, 128, 0]},
    "lcd": {"screen": "clock"},
    "macros": {
        "M1": {
            "G1":  {"type": "shell", "command": "xterm"},
            "G2":  {"type": "keystroke", "keys": "ctrl+c"},
            "G3":  {"type": "keystroke", "keys": "ctrl+z"},
            "G4":  {"type": "keystroke", "keys": "ctrl+shift+t"},
            "G5":  {"type": "shell", "command": ""},
            "G6":  {"type": "shell", "command": ""},
        },
        "M2": {},
        "M3": {},
    }
}


class Profile:
    def __init__(self, data: dict):
        self._data = data

    @property
    def name(self) -> str:
        return self._data.get("name", "unnamed")

    @property
    def rgb(self) -> dict:
        return self._data.get("rgb", {"color": [255, 128, 0]})

    @property
    def lcd(self) -> dict:
        return self._data.get("lcd", {"screen": "clock"})

    def get_macro(self, key: str, bank: str) -> Optional[dict]:
        """Return the macro dict for key+bank, or None if unbound."""
        macros = self._data.get("macros", {})
        bank_macros = macros.get(bank, {})
        return bank_macros.get(key)

    def set_macro(self, key: str, bank: str, action: dict):
        """Bind a macro. Passing an empty dict is equivalent to delete_macro."""
        if not action:
            self.delete_macro(key, bank)
            return
        self._data.setdefault("macros", {}).setdefault(bank, {})[key] = action

    def delete_macro(self, key: str, bank: str):
        try:
            del self._data["macros"][bank][key]
        except KeyError:
            pass

    def set_rgb(self, r: int, g: int, b: int):
        self._data.setdefault("rgb", {})["color"] = [r, g, b]

    def to_dict(self) -> dict:
        return dict(self._data)


class ProfileManager:
    def __init__(self, profiles_dir: Path):
        self.profiles_dir = profiles_dir
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        self.active: Profile = Profile(DEFAULT_PROFILE)

    def load_active(self, name: str = "default"):
        profile_path = self.profiles_dir / f"{name}.json"
        if not profile_path.exists():
            log.info("No profile '%s' found — creating default", name)
            self._save_profile(DEFAULT_PROFILE, profile_path)
        self.active = self._load_profile(profile_path)
        log.info("Loaded profile: %s", self.active.name)

    def save_active(self):
        path = self.profiles_dir / f"{self.active.name}.json"
        self._save_profile(self.active.to_dict(), path)

    def list_profiles(self) -> list[str]:
        return [p.stem for p in self.profiles_dir.glob("*.json")]

    def load_profile(self, name: str) -> Profile:
        path = self.profiles_dir / f"{name}.json"
        if not path.exists():
            raise FileNotFoundError(f"Profile not found: {name}")
        return self._load_profile(path)

    def switch_profile(self, name: str):
        self.active = self.load_profile(name)
        log.info("Switched to profile: %s", name)

    def create_profile(self, name: str) -> Profile:
        data = dict(DEFAULT_PROFILE)
        data["name"] = name
        path = self.profiles_dir / f"{name}.json"
        self._save_profile(data, path)
        return Profile(data)

    def delete_profile(self, name: str):
        if name == "default":
            raise ValueError("Cannot delete the default profile")
        path = self.profiles_dir / f"{name}.json"
        if path.exists():
            path.unlink()

    @staticmethod
    def _load_profile(path: Path) -> Profile:
        with open(path) as f:
            data = json.load(f)
        return Profile(data)

    @staticmethod
    def _save_profile(data: dict, path: Path):
        # Write atomically
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        tmp.replace(path)
        log.debug("Saved profile: %s", path)
