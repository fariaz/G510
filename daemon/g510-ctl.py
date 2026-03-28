#!/usr/bin/env python3
"""
g510-ctl — command-line interface to the G510 daemon via D-Bus.

Usage:
  g510-ctl status
  g510-ctl color <r> <g> <b>
  g510-ctl color red|green|blue|orange|purple|cyan|yellow|white|off
  g510-ctl lcd <screen>                 # clock|sysinfo|nowplaying|custom
  g510-ctl profile list
  g510-ctl profile switch <name>
  g510-ctl profile create <name>
  g510-ctl profile delete <name>
  g510-ctl macro list [<bank>|ALL]      # bank defaults to M1
  g510-ctl macro get <key> <bank>
  g510-ctl macro set <key> <bank> shell <command>
  g510-ctl macro set <key> <bank> keystroke <keys>
  g510-ctl macro set <key> <bank> text <text>
  g510-ctl macro set <key> <bank> script <filename>
  g510-ctl macro delete <key> <bank>
  g510-ctl macro clear <bank>           # remove all macros from a bank
  g510-ctl completions bash             # print bash completion script

Examples:
  g510-ctl color orange
  g510-ctl color 0 255 128
  g510-ctl macro set G1 M1 shell "xterm -e htop"
  g510-ctl macro set G2 M1 keystroke "ctrl+shift+t"
  g510-ctl macro list ALL
  g510-ctl profile create gaming
  g510-ctl profile switch gaming
"""

import json
import sys

NAMED_COLORS = {
    "red":    (255, 0,   0),
    "green":  (0,   255, 0),
    "blue":   (0,   0,   255),
    "orange": (255, 128, 0),
    "purple": (128, 0,   255),
    "cyan":   (0,   255, 255),
    "yellow": (255, 255, 0),
    "white":  (255, 255, 255),
    "off":    (0,   0,   0),
}

GKEYS  = [f"G{i}" for i in range(1, 19)]
BANKS  = ["M1", "M2", "M3"]
MACRO_TYPE_KEYS = {
    "shell":     "command",
    "keystroke": "keys",
    "text":      "text",
    "script":    "script",
}
LCD_SCREENS = ["clock", "sysinfo", "nowplaying", "custom"]


# ─── D-Bus helpers ────────────────────────────────────────────────────────────

def get_proxy():
    try:
        import dbus
        bus = dbus.SessionBus()
        return bus.get_object("org.g510.Daemon", "/org/g510/Daemon")
    except Exception as e:
        print(f"Error: cannot connect to g510-daemon: {e}", file=sys.stderr)
        print("Is the daemon running?  systemctl --user status g510-daemon", file=sys.stderr)
        sys.exit(1)


def call(proxy, method, *args):
    import dbus
    fn = proxy.get_dbus_method(method, "org.g510.Daemon")
    return fn(*args)


def call_json(proxy, method, *args):
    raw = call(proxy, method, *args)
    return json.loads(raw or "{}")


# ─── Commands ─────────────────────────────────────────────────────────────────

def cmd_status(proxy, args):
    st = call_json(proxy, "GetStatus")
    rgb = st.get("rgb", [0, 0, 0])
    print(f"Host           : {st.get('host', '?')}")
    if st.get("model"):
        print(f"Keyboard       : {st.get('model')}")
    print(f"Active bank    : {st.get('bank', '?')}")
    print(f"Game mode      : {'ON' if st.get('game_mode') else 'OFF'}")
    print(f"Active profile : {st.get('profile', '?')}")
    print(f"All profiles   : {', '.join(st.get('profiles', []))}")
    print(f"RGB color      : R={rgb[0]}  G={rgb[1]}  B={rgb[2]}")
    print(f"LCD screen     : {st.get('lcd_screen', '?')}")


def cmd_color(proxy, args):
    if not args:
        print("Usage: g510-ctl color <r> <g> <b>  OR  g510-ctl color <name>")
        print(f"Named colors: {', '.join(NAMED_COLORS)}")
        sys.exit(1)

    if len(args) == 1:
        name = args[0].lower()
        if name not in NAMED_COLORS:
            print(f"Unknown color '{name}'. Choose from: {', '.join(NAMED_COLORS)}")
            sys.exit(1)
        r, g, b = NAMED_COLORS[name]
    elif len(args) == 3:
        try:
            r, g, b = int(args[0]), int(args[1]), int(args[2])
            if not all(0 <= v <= 255 for v in (r, g, b)):
                raise ValueError("out of range")
        except ValueError as e:
            print(f"Color values must be integers 0–255: {e}")
            sys.exit(1)
    else:
        print("Usage: g510-ctl color <r> <g> <b>  OR  g510-ctl color <name>")
        sys.exit(1)

    call(proxy, "SetColor", r, g, b)
    print(f"RGB set to ({r}, {g}, {b})")


def cmd_lcd(proxy, args):
    if not args:
        print(f"Usage: g510-ctl lcd <screen>")
        print(f"Screens: {', '.join(LCD_SCREENS)}")
        sys.exit(1)
    screen = args[0].lower()
    if screen not in LCD_SCREENS:
        print(f"Unknown screen '{screen}'. Choose from: {', '.join(LCD_SCREENS)}")
        sys.exit(1)
    call(proxy, "SetLCDScreen", screen)
    print(f"LCD screen: {screen}")


def cmd_profile(proxy, args):
    if not args:
        print("Usage: g510-ctl profile list|switch|create|delete")
        sys.exit(1)
    subcmd = args[0].lower()

    if subcmd == "list":
        st = call_json(proxy, "GetStatus")
        active = st.get("profile", "")
        for p in list(call(proxy, "GetProfiles")):
            mark = " ◀ active" if p == active else ""
            print(f"  {p}{mark}")

    elif subcmd == "switch":
        _require_arg(args, 2, "g510-ctl profile switch <name>")
        call(proxy, "SwitchProfile", args[1])
        print(f"Switched to: {args[1]}")

    elif subcmd == "create":
        _require_arg(args, 2, "g510-ctl profile create <name>")
        call(proxy, "CreateProfile", args[1])
        print(f"Created profile: {args[1]}")

    elif subcmd == "delete":
        _require_arg(args, 2, "g510-ctl profile delete <name>")
        confirm = input(f"Delete profile '{args[1]}'? [y/N] ").strip().lower()
        if confirm != "y":
            print("Cancelled.")
            return
        call(proxy, "DeleteProfile", args[1])
        print(f"Deleted profile: {args[1]}")

    else:
        print(f"Unknown subcommand: {subcmd}")
        sys.exit(1)


def cmd_macro(proxy, args):
    if not args:
        print("Usage: g510-ctl macro list|get|set|delete|clear")
        sys.exit(1)
    subcmd = args[0].lower()

    if subcmd == "list":
        bank_arg = args[1].upper() if len(args) > 1 else "M1"
        banks = BANKS if bank_arg == "ALL" else [bank_arg]
        any_bound = False
        for bank in banks:
            header_printed = False
            for key in GKEYS:
                macro = call_json(proxy, "GetMacro", key, bank)
                if macro:
                    if not header_printed:
                        print(f"\n  Bank {bank}:")
                        header_printed = True
                    mtype = macro.get("type", "?")
                    mval  = (macro.get("command") or macro.get("keys") or
                             macro.get("text")    or macro.get("script") or
                             f"{len(macro.get('steps', []))} recorded steps")
                    print(f"    {key:<4}  {mtype:<12}  {mval}")
                    any_bound = True
        if not any_bound:
            print("  (no macros bound)")

    elif subcmd == "get":
        _require_arg(args, 3, "g510-ctl macro get <key> <bank>")
        key, bank = args[1].upper(), args[2].upper()
        macro = call_json(proxy, "GetMacro", key, bank)
        if macro:
            print(json.dumps(macro, indent=2))
        else:
            print(f"{key}/{bank}: (unbound)")

    elif subcmd == "set":
        if len(args) < 5:
            print("Usage: g510-ctl macro set <key> <bank> <type> <value...>")
            print(f"Types: {', '.join(MACRO_TYPE_KEYS)}")
            sys.exit(1)
        key, bank   = args[1].upper(), args[2].upper()
        macro_type  = args[3].lower()
        value       = " ".join(args[4:])
        field       = MACRO_TYPE_KEYS.get(macro_type)
        if field is None:
            print(f"Unknown type '{macro_type}'. Use: {', '.join(MACRO_TYPE_KEYS)}")
            sys.exit(1)
        action = {"type": macro_type, field: value}
        call(proxy, "SetMacro", key, bank, json.dumps(action))
        print(f"Set {key}/{bank}: {macro_type} → {value!r}")

    elif subcmd == "delete":
        _require_arg(args, 3, "g510-ctl macro delete <key> <bank>")
        key, bank = args[1].upper(), args[2].upper()
        try:
            call(proxy, "DeleteMacro", key, bank)
        except Exception:
            # Daemon version may not have DeleteMacro yet — fall back
            call(proxy, "SetMacro", key, bank, json.dumps({}))
        print(f"Deleted macro {key}/{bank}")

    elif subcmd == "clear":
        _require_arg(args, 2, "g510-ctl macro clear <bank>")
        bank = args[1].upper()
        banks = BANKS if bank == "ALL" else [bank]
        for b in banks:
            for key in GKEYS:
                try:
                    call(proxy, "DeleteMacro", key, b)
                except Exception:
                    call(proxy, "SetMacro", key, b, json.dumps({}))
        print(f"Cleared all macros in: {', '.join(banks)}")

    else:
        print(f"Unknown subcommand: {subcmd}")
        sys.exit(1)


def cmd_completions(proxy, args):
    """Print shell completion script."""
    shell = args[0].lower() if args else "bash"
    if shell == "bash":
        print(_BASH_COMPLETIONS)
    elif shell == "zsh":
        print(_ZSH_COMPLETIONS)
    else:
        print(f"Unknown shell: {shell}. Supported: bash, zsh")
        sys.exit(1)


# ─── Completion scripts ───────────────────────────────────────────────────────

_BASH_COMPLETIONS = r"""
# Bash completion for g510-ctl
# Source with: source <(g510-ctl completions bash)
# Or add to ~/.bashrc: source <(g510-ctl completions bash)

_g510_ctl_completions() {
    local cur prev words cword
    _init_completion || return

    local commands="status color lcd profile macro completions"
    local color_names="red green blue orange purple cyan yellow white off"
    local lcd_screens="clock sysinfo nowplaying custom"
    local banks="M1 M2 M3 ALL"
    local gkeys="G1 G2 G3 G4 G5 G6 G7 G8 G9 G10 G11 G12 G13 G14 G15 G16 G17 G18"
    local macro_types="shell keystroke text script"

    case $cword in
        1)
            COMPREPLY=($(compgen -W "$commands" -- "$cur"))
            ;;
        2)
            case $prev in
                color)
                    COMPREPLY=($(compgen -W "$color_names" -- "$cur"))
                    ;;
                lcd)
                    COMPREPLY=($(compgen -W "$lcd_screens" -- "$cur"))
                    ;;
                profile)
                    COMPREPLY=($(compgen -W "list switch create delete" -- "$cur"))
                    ;;
                macro)
                    COMPREPLY=($(compgen -W "list get set delete clear" -- "$cur"))
                    ;;
                completions)
                    COMPREPLY=($(compgen -W "bash zsh" -- "$cur"))
                    ;;
            esac
            ;;
        3)
            case ${words[1]} in
                macro)
                    case ${words[2]} in
                        list|clear)
                            COMPREPLY=($(compgen -W "$banks" -- "$cur"))
                            ;;
                        get|set|delete)
                            COMPREPLY=($(compgen -W "$gkeys" -- "$cur"))
                            ;;
                    esac
                    ;;
                profile)
                    if [[ ${words[2]} == "switch" || ${words[2]} == "delete" ]]; then
                        local profiles
                        profiles=$(g510-ctl profile list 2>/dev/null | awk '{print $1}')
                        COMPREPLY=($(compgen -W "$profiles" -- "$cur"))
                    fi
                    ;;
            esac
            ;;
        4)
            case ${words[1]} in
                macro)
                    case ${words[2]} in
                        get|set|delete)
                            COMPREPLY=($(compgen -W "$banks" -- "$cur"))
                            ;;
                    esac
                    ;;
            esac
            ;;
        5)
            if [[ ${words[1]} == "macro" && ${words[2]} == "set" ]]; then
                COMPREPLY=($(compgen -W "$macro_types" -- "$cur"))
            fi
            ;;
    esac
}

complete -F _g510_ctl_completions g510-ctl
"""

_ZSH_COMPLETIONS = r"""
# Zsh completion for g510-ctl
# Add to ~/.zshrc: source <(g510-ctl completions zsh)

_g510_ctl() {
    local state

    _arguments \
        '1:command:->command' \
        '*:args:->args' && return

    case $state in
        command)
            _values 'command' status color lcd profile macro completions
            ;;
        args)
            case $words[2] in
                color)
                    _values 'color' red green blue orange purple cyan yellow white off
                    ;;
                lcd)
                    _values 'screen' clock sysinfo nowplaying custom
                    ;;
                profile)
                    _values 'subcommand' list switch create delete
                    ;;
                macro)
                    _values 'subcommand' list get set delete clear
                    ;;
            esac
            ;;
    esac
}

compdef _g510_ctl g510-ctl
"""


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _require_arg(args, n, usage):
    if len(args) < n:
        print(f"Usage: {usage}")
        sys.exit(1)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    if sys.argv[1] in ("-V", "--version"):
        try:
            from g510 import __version__
            print(f"g510-ctl {__version__}")
        except ImportError:
            print("g510-ctl (version unknown)")
        sys.exit(0)

    cmd  = sys.argv[1].lower()
    args = sys.argv[2:]

    # completions doesn't need a live daemon
    if cmd in ("completions", "completion"):
        cmd_completions(None, args)
        return

    proxy = get_proxy()

    dispatch = {
        "status":      cmd_status,
        "color":       cmd_color,
        "colour":      cmd_color,
        "lcd":         cmd_lcd,
        "profile":     cmd_profile,
        "macro":       cmd_macro,
        "completions": cmd_completions,
    }

    fn = dispatch.get(cmd)
    if fn is None:
        print(f"Unknown command: {cmd}\n")
        print(__doc__)
        sys.exit(1)

    fn(proxy, args)


if __name__ == "__main__":
    main()
