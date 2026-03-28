#!/usr/bin/env python3
"""
g510-daemon — userspace daemon for the Logitech G510/G510s keyboard on Linux.

Handles:
  - G-key macro execution (G1–G18, M1/M2/M3/MR bank switching)
  - Media/audio key pass-through and volume wheel
  - RGB backlight control (via sysfs LEDs or direct USB)
  - LCD GamePanel display rendering
  - D-Bus interface for GUI communication
  - Profile management (JSON-based)

Requires: python-evdev, Pillow, dbus-python
"""

import os
import sys
import signal
import logging
import argparse
import threading
import time
from pathlib import Path

# Local modules
sys.path.insert(0, str(Path(__file__).parent))
from g510.config     import Config
from g510.keyboard   import G510Keyboard
from g510.macros     import MacroEngine
from g510.lcd        import LCDManager
from g510.rgb        import RGBController
from g510.profiles   import ProfileManager
from g510.dbus_iface import DBusInterface

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logging.basicConfig(format=LOG_FORMAT, level=logging.INFO)
log = logging.getLogger("g510d")


def parse_args():
    from g510 import __version__
    p = argparse.ArgumentParser(description="Logitech G510/G510s daemon")
    p.add_argument("-c", "--config", default="~/.config/g510/config.toml",
                   help="Path to config file")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--no-dbus", action="store_true", help="Disable D-Bus interface")
    p.add_argument("--no-lcd",  action="store_true", help="Disable LCD manager")
    p.add_argument("--version",  action="version", version=f"g510-daemon {__version__}")
    return p.parse_args()


def main():
    args = parse_args()
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    config_path = Path(args.config).expanduser()
    log.info("Loading config from %s", config_path)
    config = Config(config_path)

    # Profile manager — loads/saves macro + color profiles
    profiles = ProfileManager(config.profiles_dir)
    profiles.load_active()

    # RGB controller — sysfs-first, falls back to direct USB via libg15
    rgb = RGBController(config)
    rgb.apply(profiles.active.rgb)

    # LCD manager — renders frames to the 160×43 monochrome display
    lcd = None
    if not args.no_lcd:
        lcd = LCDManager(config, profile=profiles.active)
        lcd.start()

    # Macro engine — maps G-key events to actions
    macro_engine = MacroEngine(profiles, config)

    # Keyboard input listener
    keyboard = G510Keyboard(config, macro_engine, rgb, lcd, profiles)

    # D-Bus interface for GUI
    dbus_iface = None
    if not args.no_dbus:
        try:
            dbus_iface = DBusInterface(keyboard, profiles, rgb, lcd)
            dbus_thread = threading.Thread(target=dbus_iface.run, daemon=True)
            dbus_thread.start()
            log.info("D-Bus interface started")
        except Exception as e:
            log.warning("D-Bus interface failed to start: %s", e)

    # Graceful shutdown
    def shutdown(sig, frame):
        log.info("Shutting down (signal %s)…", sig)
        keyboard.stop()
        if lcd:
            lcd.stop()
        if dbus_iface:
            dbus_iface.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT,  shutdown)

    log.info("g510-daemon started. Listening for events…")
    keyboard.run()  # blocks


if __name__ == "__main__":
    main()
