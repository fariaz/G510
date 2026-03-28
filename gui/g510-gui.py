#!/usr/bin/env python3
"""
g510-gui — GTK3 control panel for the Logitech G510 daemon.
Designed for LXQt and other X11 desktops.

Requires: GTK3, python3-gi, gir1.2-gtk-3.0, dbus-python
"""

import json
import logging
import sys
import os
from pathlib import Path

log = logging.getLogger("g510-gui")

try:
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, Gdk, GLib, Gio
except Exception as e:
    print(f"GTK3 not available: {e}")
    print("Install: sudo apt install python3-gi gir1.2-gtk-3.0")
    sys.exit(1)

try:
    import dbus
    import dbus.mainloop.glib
    HAS_DBUS = True
except ImportError:
    HAS_DBUS = False
    log.warning("dbus-python not installed — running offline")

DBUS_SERVICE = "org.g510.Daemon"
DBUS_PATH    = "/org/g510/Daemon"
DBUS_IFACE   = "org.g510.Daemon"

GKEYS       = [f"G{i}" for i in range(1, 19)]
BANKS       = ["M1", "M2", "M3"]
MACRO_TYPES = ["shell", "keystroke", "text", "script"]
LCD_SCREENS = ["clock", "sysinfo", "nowplaying", "custom"]


# ─── D-Bus proxy ──────────────────────────────────────────────────────────────

class DaemonProxy:
    def __init__(self):
        self._proxy = None
        if HAS_DBUS:
            try:
                dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
                bus = dbus.SessionBus()
                self._proxy = bus.get_object(DBUS_SERVICE, DBUS_PATH)
            except dbus.DBusException:
                log.warning("Daemon not running")

    def available(self) -> bool:
        return self._proxy is not None

    def call(self, method, *args):
        if not self._proxy:
            return None
        try:
            fn = self._proxy.get_dbus_method(method, DBUS_IFACE)
            return fn(*args)
        except Exception as e:
            log.debug("D-Bus %s failed: %s", method, e)
            return None

    def get_profiles(self):    return list(self.call("GetProfiles") or [])
    def switch_profile(self, n): self.call("SwitchProfile", n)
    def set_color(self, r,g,b):  self.call("SetColor", r, g, b)
    def get_macro(self, k, b):   return json.loads(self.call("GetMacro", k, b) or "{}")
    def set_macro(self, k, b, a): self.call("SetMacro", k, b, json.dumps(a))
    def delete_macro(self, k, b): self.call("DeleteMacro", k, b)
    def set_lcd_screen(self, n):  self.call("SetLCDScreen", n)
    def get_status(self):         return json.loads(self.call("GetStatus") or "{}")
    def create_profile(self, n):  self.call("CreateProfile", n)
    def delete_profile(self, n):  self.call("DeleteProfile", n)


# ─── Macro edit dialog ────────────────────────────────────────────────────────

class MacroEditDialog(Gtk.Dialog):
    def __init__(self, parent, key, bank, macro, on_save):
        super().__init__(title=f"Edit macro — {key} / {bank}",
                         transient_for=parent, modal=True,
                         destroy_with_parent=True)
        self.set_default_size(420, 260)
        self._on_save = on_save
        self._key = key
        self._bank = bank

        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        ok_btn = self.add_button("Save", Gtk.ResponseType.OK)
        ok_btn.get_style_context().add_class("suggested-action")

        box = self.get_content_area()
        box.set_spacing(12)
        box.set_margin_top(16); box.set_margin_bottom(16)
        box.set_margin_start(16); box.set_margin_end(16)

        # Type combo
        grid = Gtk.Grid(row_spacing=8, column_spacing=12)
        grid.attach(Gtk.Label(label="Type:", xalign=0), 0, 0, 1, 1)
        self._type_combo = Gtk.ComboBoxText()
        for t in MACRO_TYPES:
            self._type_combo.append_text(t)
        cur = macro.get("type", "shell") if macro else "shell"
        self._type_combo.set_active(MACRO_TYPES.index(cur) if cur in MACRO_TYPES else 0)
        grid.attach(self._type_combo, 1, 0, 1, 1)

        # Value entry
        grid.attach(Gtk.Label(label="Value:", xalign=0), 0, 1, 1, 1)
        self._entry = Gtk.Entry()
        self._entry.set_hexpand(True)
        val = (macro.get("command") or macro.get("keys") or
               macro.get("text")    or macro.get("script") or "") if macro else ""
        self._entry.set_text(val)
        self._entry.set_placeholder_text("command / key combo / text / script name")
        grid.attach(self._entry, 1, 1, 1, 1)

        # Hint
        hint = Gtk.Label(
            label="keystroke: ctrl+shift+t   shell: xterm   text: hello",
            xalign=0
        )
        hint.get_style_context().add_class("dim-label")
        grid.attach(hint, 0, 2, 2, 1)

        box.pack_start(grid, True, True, 0)
        self.show_all()

    def get_action(self):
        idx   = self._type_combo.get_active()
        mtype = MACRO_TYPES[idx] if idx >= 0 else "shell"
        value = self._entry.get_text().strip()
        field_map = {"shell":"command","keystroke":"keys","text":"text","script":"script"}
        return {"type": mtype, field_map[mtype]: value}


# ─── Main window ──────────────────────────────────────────────────────────────

class G510Window(Gtk.Window):
    def __init__(self, proxy: DaemonProxy):
        super().__init__(title="G510 Control Panel")
        self.set_default_size(700, 520)
        self.set_border_width(0)
        self._proxy       = proxy
        self._active_bank = "M1"
        self._profiles    = []
        self.connect("destroy", Gtk.main_quit)

        # Top-level layout: header bar + notebook
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(vbox)

        # Header bar (GTK3 native, works in LXQt)
        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        header.set_title("G510 Control Panel")

        # Bank indicator in header
        self._bank_label = Gtk.Label(label="M1")
        self._bank_label.set_tooltip_text("Active macro bank")
        ctx = self._bank_label.get_style_context()
        ctx.add_class("heading")
        header.pack_end(self._bank_label)

        if not proxy.available():
            offline = Gtk.Label(label="● daemon offline")
            offline.get_style_context().add_class("dim-label")
            header.pack_start(offline)

        self.set_titlebar(header)

        # Notebook tabs
        nb = Gtk.Notebook()
        nb.set_tab_pos(Gtk.PositionType.TOP)
        vbox.pack_start(nb, True, True, 0)

        nb.append_page(self._build_macros_page(),   Gtk.Label(label="Macros"))
        nb.append_page(self._build_rgb_page(),      Gtk.Label(label="Backlight"))
        nb.append_page(self._build_lcd_page(),      Gtk.Label(label="LCD"))
        nb.append_page(self._build_profiles_page(), Gtk.Label(label="Profiles"))

        self._refresh_profiles()
        self._refresh_macros()
        GLib.timeout_add(2000, self._poll_status)

    # ── Macros page ───────────────────────────────────────────────────────────

    def _build_macros_page(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        vbox.set_border_width(8)

        # Bank selector
        bank_box = Gtk.Box(spacing=4)
        bank_box.set_halign(Gtk.Align.CENTER)
        self._bank_buttons = {}
        grp = None
        for bank in BANKS:
            btn = Gtk.RadioButton.new_with_label_from_widget(grp, bank)
            if grp is None:
                grp = btn
            btn.connect("toggled", self._on_bank_toggled, bank)
            if bank == "M1":
                btn.set_active(True)
            bank_box.pack_start(btn, False, False, 0)
            self._bank_buttons[bank] = btn
        vbox.pack_start(bank_box, False, False, 0)

        # Scrolled macro list
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._macro_store = Gtk.ListStore(str, str, str)   # key, type, value
        tv = Gtk.TreeView(model=self._macro_store)
        tv.set_headers_visible(True)
        tv.connect("row-activated", self._on_macro_row_activated)
        self._macro_tv = tv

        for i, title in enumerate(["Key", "Type", "Value"]):
            col = Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=i)
            col.set_resizable(True)
            if i == 2:
                col.set_expand(True)
            tv.append_column(col)

        scroll.add(tv)
        vbox.pack_start(scroll, True, True, 0)

        # Action buttons
        btn_box = Gtk.ButtonBox(orientation=Gtk.Orientation.HORIZONTAL)
        btn_box.set_layout(Gtk.ButtonBoxStyle.START)
        btn_box.set_spacing(6)

        edit_btn = Gtk.Button.new_with_label("Edit")
        edit_btn.connect("clicked", self._on_macro_edit_clicked)
        del_btn = Gtk.Button.new_with_label("Delete")
        del_btn.connect("clicked", self._on_macro_delete_clicked)
        del_btn.get_style_context().add_class("destructive-action")

        btn_box.pack_start(edit_btn, False, False, 0)
        btn_box.pack_start(del_btn, False, False, 0)
        vbox.pack_start(btn_box, False, False, 0)

        return vbox

    def _on_bank_toggled(self, btn, bank):
        if btn.get_active():
            self._active_bank = bank
            self._refresh_macros()

    def _refresh_macros(self):
        self._macro_store.clear()
        bank = self._active_bank
        for key in GKEYS:
            macro = self._proxy.get_macro(key, bank) if self._proxy.available() else {}
            if macro:
                mtype = macro.get("type", "")
                mval  = (macro.get("command") or macro.get("keys") or
                         macro.get("text")    or macro.get("script") or
                         f"{len(macro.get('steps',[]))} steps")
                self._macro_store.append([key, mtype, mval])
            else:
                self._macro_store.append([key, "", "(unbound)"])

    def _selected_key(self):
        sel = self._macro_tv.get_selection()
        model, it = sel.get_selected()
        if it:
            return model[it][0]
        return None

    def _on_macro_row_activated(self, tv, path, col):
        self._open_macro_editor()

    def _on_macro_edit_clicked(self, _):
        self._open_macro_editor()

    def _open_macro_editor(self):
        key = self._selected_key()
        if not key:
            return
        macro = self._proxy.get_macro(key, self._active_bank) if self._proxy.available() else {}
        dlg = MacroEditDialog(self, key, self._active_bank, macro or None,
                              on_save=self._save_macro)
        resp = dlg.run()
        if resp == Gtk.ResponseType.OK:
            action = dlg.get_action()
            if action.get(list(action.keys())[1] if len(action)>1 else "command", ""):
                self._proxy.set_macro(key, self._active_bank, action)
            else:
                self._proxy.delete_macro(key, self._active_bank)
            GLib.idle_add(self._refresh_macros)
        dlg.destroy()

    def _save_macro(self, key, bank, action):
        self._proxy.set_macro(key, bank, action)
        GLib.idle_add(self._refresh_macros)

    def _on_macro_delete_clicked(self, _):
        key = self._selected_key()
        if not key:
            return
        self._proxy.delete_macro(key, self._active_bank)
        GLib.idle_add(self._refresh_macros)

    # ── RGB page ──────────────────────────────────────────────────────────────

    def _build_rgb_page(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        vbox.set_border_width(16)
        vbox.set_valign(Gtk.Align.CENTER)

        lbl = Gtk.Label(label="Keyboard backlight colour")
        lbl.get_style_context().add_class("h2")
        vbox.pack_start(lbl, False, False, 0)

        # Colour preview swatch
        self._color_preview = Gtk.DrawingArea()
        self._color_preview.set_size_request(200, 50)
        self._color_preview.set_halign(Gtk.Align.CENTER)
        self._rgb_values = [255, 128, 0]
        self._color_preview.connect("draw", self._draw_color_preview)
        vbox.pack_start(self._color_preview, False, False, 0)

        # Named colour buttons
        colour_flow = Gtk.FlowBox()
        colour_flow.set_max_children_per_line(5)
        colour_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        colour_flow.set_halign(Gtk.Align.CENTER)
        NAMED = [("Red",(255,0,0)),("Green",(0,255,0)),("Blue",(0,0,255)),
                 ("Orange",(255,128,0)),("Purple",(128,0,255)),
                 ("Cyan",(0,255,255)),("White",(255,255,255)),("Off",(0,0,0))]
        for name, (r,g,b) in NAMED:
            btn = Gtk.Button(label=name)
            btn.connect("clicked", lambda _, rv=(r,g,b): self._apply_named(rv))
            colour_flow.add(btn)
        vbox.pack_start(colour_flow, False, False, 0)

        # RGB sliders
        grid = Gtk.Grid(row_spacing=8, column_spacing=12)
        grid.set_halign(Gtk.Align.CENTER)
        self._sliders = {}
        for row, (ch, label, default) in enumerate([("R","Red",255),("G","Green",128),("B","Blue",0)]):
            grid.attach(Gtk.Label(label=label+":", xalign=1), 0, row, 1, 1)
            sl = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 255, 1)
            sl.set_value(default)
            sl.set_size_request(220, -1)
            sl.set_draw_value(True)
            sl.connect("value-changed", self._on_slider_changed)
            grid.attach(sl, 1, row, 1, 1)
            self._sliders[ch] = sl
        vbox.pack_start(grid, False, False, 0)

        apply_btn = Gtk.Button(label="Apply colour")
        apply_btn.get_style_context().add_class("suggested-action")
        apply_btn.set_halign(Gtk.Align.CENTER)
        apply_btn.connect("clicked", self._apply_color)
        vbox.pack_start(apply_btn, False, False, 0)

        return vbox

    def _draw_color_preview(self, widget, cr):
        r, g, b = [v/255.0 for v in self._rgb_values]
        cr.set_source_rgb(r, g, b)
        cr.paint()

    def _apply_named(self, rgb):
        r, g, b = rgb
        self._sliders["R"].set_value(r)
        self._sliders["G"].set_value(g)
        self._sliders["B"].set_value(b)
        self._rgb_values = [r, g, b]
        self._color_preview.queue_draw()
        self._proxy.set_color(r, g, b)

    def _on_slider_changed(self, _):
        self._rgb_values = [int(self._sliders[c].get_value()) for c in "RGB"]
        self._color_preview.queue_draw()

    def _apply_color(self, _):
        r, g, b = self._rgb_values
        self._proxy.set_color(r, g, b)

    # ── LCD page ──────────────────────────────────────────────────────────────

    def _build_lcd_page(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        vbox.set_border_width(16)
        vbox.set_valign(Gtk.Align.CENTER)

        lbl = Gtk.Label(label="LCD GamePanel screen")
        lbl.get_style_context().add_class("h2")
        vbox.pack_start(lbl, False, False, 0)

        # LCD preview canvas (3× scale: 480×129)
        SCALE = 3
        self._lcd_preview = Gtk.DrawingArea()
        self._lcd_preview.set_size_request(160 * SCALE, 43 * SCALE)
        self._lcd_preview.set_halign(Gtk.Align.CENTER)
        self._lcd_pixels = [[1]*160 for _ in range(43)]
        self._lcd_preview.connect("draw", self._draw_lcd)
        vbox.pack_start(self._lcd_preview, False, False, 0)

        refresh_btn = Gtk.Button(label="Refresh preview")
        refresh_btn.set_halign(Gtk.Align.CENTER)
        refresh_btn.connect("clicked", lambda _: self._refresh_lcd_preview())
        vbox.pack_start(refresh_btn, False, False, 0)

        # Screen radio buttons
        frame = Gtk.Frame(label="Screen")
        screen_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        screen_box.set_border_width(8)
        frame.add(screen_box)

        SCREENS = [("clock","Clock — HH:MM:SS + date"),
                   ("sysinfo","System info — CPU, memory, time"),
                   ("nowplaying","Now playing — media title + progress"),
                   ("custom","Custom — text from profile")]
        self._screen_buttons = {}
        grp = None
        for sid, desc in SCREENS:
            btn = Gtk.RadioButton.new_with_label_from_widget(grp, desc)
            if grp is None:
                grp = btn
            if sid == "clock":
                btn.set_active(True)
            btn.connect("toggled", self._on_lcd_toggled, sid)
            screen_box.pack_start(btn, False, False, 0)
            self._screen_buttons[sid] = btn

        vbox.pack_start(frame, False, False, 0)
        return vbox

    def _draw_lcd(self, widget, cr):
        SCALE = 3
        cr.set_source_rgb(0.12, 0.12, 0.12)
        cr.paint()
        cr.set_source_rgb(0.85, 0.95, 0.78)
        for row in range(43):
            for col in range(160):
                if self._lcd_pixels[row][col] == 0:
                    cr.rectangle(col*SCALE, row*SCALE, SCALE-1, SCALE-1)
        cr.fill()

    def _refresh_lcd_preview(self):
        try:
            sys.path.insert(0, str(Path(__file__).parent.parent / "daemon"))
            from g510.lcd import ClockScreen, SysInfoScreen, NowPlayingScreen
            active = next((s for s, b in self._screen_buttons.items() if b.get_active()), "clock")
            screens = {"clock": ClockScreen(), "sysinfo": SysInfoScreen(),
                       "nowplaying": NowPlayingScreen()}
            screen = screens.get(active)
            if screen:
                img = screen.render().convert("1")
                px  = img.load()
                self._lcd_pixels = [[px[col,row] for col in range(160)] for row in range(43)]
                self._lcd_preview.queue_draw()
        except Exception as e:
            log.debug("LCD preview: %s", e)

    def _on_lcd_toggled(self, btn, sid):
        if btn.get_active():
            self._proxy.set_lcd_screen(sid)
            GLib.idle_add(self._refresh_lcd_preview)

    # ── Profiles page ─────────────────────────────────────────────────────────

    def _build_profiles_page(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        vbox.set_border_width(8)

        lbl = Gtk.Label(label="Profiles", xalign=0)
        lbl.get_style_context().add_class("h2")
        vbox.pack_start(lbl, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._profile_store = Gtk.ListStore(str)
        tv = Gtk.TreeView(model=self._profile_store)
        tv.set_headers_visible(False)
        col = Gtk.TreeViewColumn("Profile", Gtk.CellRendererText(), text=0)
        tv.append_column(col)
        tv.connect("row-activated", self._on_profile_activated)
        self._profile_tv = tv
        scroll.add(tv)
        vbox.pack_start(scroll, True, True, 0)

        # New profile row
        new_box = Gtk.Box(spacing=6)
        self._new_profile_entry = Gtk.Entry()
        self._new_profile_entry.set_placeholder_text("New profile name")
        self._new_profile_entry.set_hexpand(True)
        self._new_profile_entry.connect("activate", self._create_profile)
        new_box.pack_start(self._new_profile_entry, True, True, 0)
        create_btn = Gtk.Button(label="Create")
        create_btn.get_style_context().add_class("suggested-action")
        create_btn.connect("clicked", self._create_profile)
        new_box.pack_start(create_btn, False, False, 0)
        vbox.pack_start(new_box, False, False, 0)

        # Action buttons
        btn_box = Gtk.ButtonBox(orientation=Gtk.Orientation.HORIZONTAL)
        btn_box.set_layout(Gtk.ButtonBoxStyle.START)
        btn_box.set_spacing(6)

        switch_btn = Gtk.Button(label="Switch to selected")
        switch_btn.get_style_context().add_class("suggested-action")
        switch_btn.connect("clicked", self._switch_profile)

        export_btn = Gtk.Button(label="Export…")
        export_btn.connect("clicked", self._export_profile)

        import_btn = Gtk.Button(label="Import…")
        import_btn.connect("clicked", self._import_profile)

        del_btn = Gtk.Button(label="Delete")
        del_btn.get_style_context().add_class("destructive-action")
        del_btn.connect("clicked", self._delete_profile)

        for b in [switch_btn, export_btn, import_btn, del_btn]:
            btn_box.pack_start(b, False, False, 0)
        vbox.pack_start(btn_box, False, False, 0)

        return vbox

    def _refresh_profiles(self):
        self._profile_store.clear()
        self._profiles = self._proxy.get_profiles()
        for p in self._profiles:
            self._profile_store.append([p])

    def _selected_profile_name(self):
        sel = self._profile_tv.get_selection()
        model, it = sel.get_selected()
        if it:
            return model[it][0]
        return None

    def _on_profile_activated(self, tv, path, col):
        name = self._profile_store[path][0]
        self._proxy.switch_profile(name)
        self._refresh_macros()

    def _switch_profile(self, _):
        name = self._selected_profile_name()
        if name:
            self._proxy.switch_profile(name)
            self._refresh_macros()

    def _create_profile(self, _):
        name = self._new_profile_entry.get_text().strip()
        if not name:
            return
        try:
            self._proxy.create_profile(name)
        except Exception:
            dest = Path.home() / ".config/g510/profiles" / f"{name}.json"
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                dest.write_text(json.dumps({"name": name, "rgb": {"color": [255,128,0]},
                    "lcd": {"screen": "clock"}, "macros": {"M1":{},"M2":{},"M3":{}}}, indent=2))
        self._new_profile_entry.set_text("")
        GLib.idle_add(self._refresh_profiles)

    def _delete_profile(self, _):
        name = self._selected_profile_name()
        if not name:
            return
        if name == "default":
            self._show_message("Cannot delete the default profile.", Gtk.MessageType.WARNING)
            return
        dlg = Gtk.MessageDialog(transient_for=self, modal=True,
                                message_type=Gtk.MessageType.QUESTION,
                                buttons=Gtk.ButtonsType.YES_NO,
                                text=f"Delete profile '{name}'?")
        dlg.format_secondary_text("This cannot be undone.")
        resp = dlg.run()
        dlg.destroy()
        if resp == Gtk.ResponseType.YES:
            try:
                self._proxy.delete_profile(name)
            except Exception:
                p = Path.home() / ".config/g510/profiles" / f"{name}.json"
                if p.exists():
                    p.unlink()
            GLib.idle_add(self._refresh_profiles)

    def _export_profile(self, _):
        dlg = Gtk.FileChooserDialog(title="Export profile", transient_for=self,
                                    action=Gtk.FileChooserAction.SAVE)
        dlg.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("Save",   Gtk.ResponseType.ACCEPT)
        ff = Gtk.FileFilter(); ff.set_name("JSON (*.json)"); ff.add_pattern("*.json")
        dlg.add_filter(ff)
        st = self._proxy.get_status()
        dlg.set_current_name(f"{st.get('profile','profile')}.json")
        if dlg.run() == Gtk.ResponseType.ACCEPT:
            import shutil
            src = Path.home() / ".config/g510/profiles" / f"{st.get('profile','default')}.json"
            dst = Path(dlg.get_filename())
            if src.exists():
                shutil.copy2(src, dst)
                self._show_message(f"Exported to {dst.name}")
        dlg.destroy()

    def _import_profile(self, _):
        dlg = Gtk.FileChooserDialog(title="Import profile", transient_for=self,
                                    action=Gtk.FileChooserAction.OPEN)
        dlg.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("Import", Gtk.ResponseType.ACCEPT)
        ff = Gtk.FileFilter(); ff.set_name("JSON (*.json)"); ff.add_pattern("*.json")
        dlg.add_filter(ff)
        if dlg.run() == Gtk.ResponseType.ACCEPT:
            try:
                src = Path(dlg.get_filename())
                data = json.loads(src.read_text())
                name = data.get("name", src.stem)
                dest = Path.home() / ".config/g510/profiles" / f"{name}.json"
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(json.dumps(data, indent=2))
                GLib.idle_add(self._refresh_profiles)
                self._show_message(f"Imported profile '{name}'")
            except Exception as e:
                self._show_message(f"Import failed: {e}", Gtk.MessageType.ERROR)
        dlg.destroy()

    # ── Status poll & utilities ───────────────────────────────────────────────

    def _poll_status(self) -> bool:
        if not self._proxy.available():
            return True
        try:
            st = self._proxy.get_status()
            bank = st.get("bank", "")
            if bank:
                self._bank_label.set_label(bank)
                tip = f"Bank: {bank}"
                if st.get("game_mode"):
                    tip += "  |  Game mode ON"
                self._bank_label.set_tooltip_text(tip)
        except Exception:
            pass
        return True

    def _show_message(self, msg, mtype=Gtk.MessageType.INFO):
        dlg = Gtk.MessageDialog(transient_for=self, modal=True,
                                message_type=mtype, buttons=Gtk.ButtonsType.OK,
                                text=msg)
        dlg.run(); dlg.destroy()


# ─── Entry point ──────────────────────────────────────────────────────────────

def main():
    logging.basicConfig(level=logging.INFO)
    proxy = DaemonProxy()
    win   = G510Window(proxy)
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
