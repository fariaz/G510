"""
g510.dbus_iface — D-Bus interface for GUI ↔ daemon communication.

Service name: org.g510.Daemon
Object path:  /org/g510/Daemon

Methods:
  GetProfiles()          → list[str]
  SwitchProfile(name)    → void
  SetColor(r, g, b)      → void
  GetMacro(key, bank)    → dict (as JSON string)
  SetMacro(key, bank, action_json) → void
  SetLCDScreen(name)     → void
  GetStatus()            → dict (as JSON string)

Signals:
  ProfileChanged(name)
  BankChanged(bank)
"""

import json
import logging
import threading

log = logging.getLogger(__name__)

DBUS_SERVICE = "org.g510.Daemon"
DBUS_PATH    = "/org/g510/Daemon"
DBUS_IFACE   = "org.g510.Daemon"

try:
    import dbus
    import dbus.service
    import dbus.mainloop.glib
    from gi.repository import GLib
    HAS_DBUS = True
except ImportError:
    HAS_DBUS = False
    log.warning("dbus-python or gi not installed — D-Bus interface disabled")


class DBusInterface:
    def __init__(self, keyboard, profiles, rgb, lcd):
        self._keyboard = keyboard
        self._profiles = profiles
        self._rgb      = rgb
        self._lcd      = lcd
        self._mainloop = None
        self._service  = None

    def run(self):
        if not HAS_DBUS:
            return
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        bus = dbus.SessionBus()
        bus_name = dbus.service.BusName(DBUS_SERVICE, bus)
        self._service = G510DBusService(bus, bus_name, self._profiles, self._rgb, self._lcd, keyboard=self._keyboard)
        # Wire keyboard → D-Bus BankChanged signal
        if self._keyboard and hasattr(self._keyboard, "set_bank_changed_callback"):
            self._keyboard.set_bank_changed_callback(self._service.BankChanged)
        self._mainloop = GLib.MainLoop()
        log.info("D-Bus service started: %s", DBUS_SERVICE)
        self._mainloop.run()

    def stop(self):
        if self._mainloop:
            self._mainloop.quit()


if HAS_DBUS:
    class G510DBusService(dbus.service.Object):
        def __init__(self, bus, bus_name, profiles, rgb, lcd, keyboard=None):
            dbus.service.Object.__init__(self, bus_name, DBUS_PATH)
            self._profiles = profiles
            self._rgb      = rgb
            self._lcd      = lcd
            self._keyboard = keyboard

        @dbus.service.method(DBUS_IFACE, in_signature="", out_signature="as")
        def GetProfiles(self):
            return self._profiles.list_profiles()

        @dbus.service.method(DBUS_IFACE, in_signature="s", out_signature="")
        def SwitchProfile(self, name):
            try:
                self._profiles.switch_profile(str(name))
                self.ProfileChanged(str(name))
            except Exception as e:
                raise dbus.exceptions.DBusException(str(e))

        @dbus.service.method(DBUS_IFACE, in_signature="yyy", out_signature="")
        def SetColor(self, r, g, b):
            self._rgb.set_color(int(r), int(g), int(b))
            self._profiles.active.set_rgb(int(r), int(g), int(b))
            self._profiles.save_active()

        @dbus.service.method(DBUS_IFACE, in_signature="ss", out_signature="s")
        def GetMacro(self, key, bank):
            macro = self._profiles.active.get_macro(str(key), str(bank))
            return json.dumps(macro or {})

        @dbus.service.method(DBUS_IFACE, in_signature="sss", out_signature="")
        def SetMacro(self, key, bank, action_json):
            action = json.loads(str(action_json))
            self._profiles.active.set_macro(str(key), str(bank), action)
            self._profiles.save_active()

        @dbus.service.method(DBUS_IFACE, in_signature="s", out_signature="")
        def SetLCDScreen(self, name):
            if self._lcd:
                self._lcd.set_screen(str(name), _profile_mgr=self._profiles)

        @dbus.service.method(DBUS_IFACE, in_signature="s", out_signature="")
        def CreateProfile(self, name):
            try:
                self._profiles.create_profile(str(name))
                self.ProfileChanged(str(name))
            except Exception as e:
                raise dbus.exceptions.DBusException(str(e))

        @dbus.service.method(DBUS_IFACE, in_signature="s", out_signature="")
        def DeleteProfile(self, name):
            try:
                self._profiles.delete_profile(str(name))
                # Signal with empty string to indicate deletion
                self.ProfileChanged("")
            except Exception as e:
                raise dbus.exceptions.DBusException(str(e))

        @dbus.service.method(DBUS_IFACE, in_signature="ss", out_signature="")
        def DeleteMacro(self, key, bank):
            """Unbind a single macro key."""
            self._profiles.active.delete_macro(str(key), str(bank))
            self._profiles.save_active()

        @dbus.service.method(DBUS_IFACE, in_signature="", out_signature="s")
        def GetStatus(self):
            import platform
            active = self._profiles.active
            # Include model info if the keyboard object was passed in
            model_info = {}
            if hasattr(self, "_keyboard") and self._keyboard:
                kb = self._keyboard
                if hasattr(kb, "_model") and hasattr(kb, "_caps"):
                    from g510.model import model_name
                    model_info = {
                        "model":      model_name(kb._model),
                        "game_mode":  kb._game_mode,
                        "bank":       kb._current_mbank,
                    }
            return json.dumps({
                "profile":    active.name,
                "profiles":   self._profiles.list_profiles(),
                "rgb":        active.rgb.get("color", [0, 0, 0]),
                "lcd_screen": active.lcd.get("screen", "clock"),
                "host":       platform.node(),
                **model_info,
            })

        @dbus.service.signal(DBUS_IFACE, signature="s")
        def ProfileChanged(self, name):
            pass

        @dbus.service.signal(DBUS_IFACE, signature="s")
        def BankChanged(self, bank):
            pass
