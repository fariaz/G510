#!/usr/bin/env bash
# g510-verify.sh — verify kernel support and detect Logitech G510/G510s
# Run this before starting the daemon.

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BOLD='\033[1m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC}    $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail() { echo -e "${RED}[FAIL]${NC}  $*"; }
info() { echo -e "${BOLD}[INFO]${NC}  $*"; }

# Known PIDs
declare -A PID_NAMES=(
    ["c22d"]="G510 (no headset)"
    ["c22e"]="G510 (headset/audio active)"
    ["c24d"]="G510s (no headset)"
    ["c24e"]="G510s (headset/audio active)"
)

echo -e "${BOLD}=== Logitech G510/G510s Linux setup verifier ===${NC}"
echo

# ── Quick diagnosis for common startup errors ─────────────────────────────────
echo -e "${BOLD}--- Quick diagnosis ---${NC}"

# Check groups immediately — this is the #1 cause of all three common errors
_MISSING=()
for _grp in plugdev input; do
    groups | grep -qw "$_grp" || _MISSING+=("$_grp")
done

if [ ${#_MISSING[@]} -gt 0 ]; then
    echo -e "${RED}[LIKELY CAUSE] User '$USER' is missing groups: ${_MISSING[*]}${NC}"
    echo ""
    echo "  This causes ALL of these symptoms:"
    echo "    • python-evdev not working / no keyboard devices found"
    echo "    • RGB backend unavailable"
    echo "    • hidraw not accessible (LCD disabled)"
    echo ""
    echo -e "${BOLD}  Fix (run BOTH, then log out and back in):${NC}"
    for _grp in "${_MISSING[@]}"; do
        echo "    sudo usermod -aG $_grp \$USER"
    done
    echo ""
    echo "  To test immediately without re-login:"
    echo "    newgrp plugdev"
    echo ""
else
    ok "User is in plugdev and input groups"
fi

# Check pyusb (needed for RGB if sysfs LEDs unavailable)
if ! python3 -c "import usb" 2>/dev/null; then
    warn "python3-usb not installed (needed for USB direct RGB)"
    echo -e "  ${YELLOW}↳ FIX: sudo apt install python3-usb${NC}"
fi

echo

# ── 1. Kernel module ──────────────────────────────────────────────────────────
echo -e "${BOLD}--- Kernel module ---${NC}"
if lsmod | grep -q hid_lg_g15; then
    ok "hid-lg-g15 module loaded"
elif modinfo hid-lg-g15 &>/dev/null; then
    warn "hid-lg-g15 available but not loaded"
    echo -e "  ${YELLOW}↳ FIX: sudo modprobe hid-lg-g15${NC}"
    if sudo modprobe hid-lg-g15 2>/dev/null; then
        ok "hid-lg-g15 loaded successfully"
    else
        fail "Could not load hid-lg-g15 — check: dmesg | tail -20"
    fi
else
    fail "hid-lg-g15 module not found — kernel may be too old (need 5.5+)"
    info "Current kernel: $(uname -r)"
fi
echo

# ── 2. USB detection ──────────────────────────────────────────────────────────
echo -e "${BOLD}--- USB device ---${NC}"
DETECTED_MODEL="none"
AUDIO_ACTIVE=false

for pid in c22d c22e c24d c24e; do
    LINE=$(lsusb | grep -i "046d:${pid}" || true)
    if [[ -n "$LINE" ]]; then
        name="${PID_NAMES[$pid]}"
        ok "Found: $name  (PID 046d:$pid)"
        case "$pid" in
            c22d|c22e) DETECTED_MODEL="G510" ;;
            c24d|c24e) DETECTED_MODEL="G510s" ;;
        esac
        if [[ "$pid" == "c22e" || "$pid" == "c24e" ]]; then
            AUDIO_ACTIVE=true
        fi
    fi
done

if [[ "$DETECTED_MODEL" == "none" ]]; then
    fail "No G510/G510s found on USB bus — is the keyboard plugged in?"
else
    info "Model: $DETECTED_MODEL  |  Audio interface active: $AUDIO_ACTIVE"
fi
echo

# ── 3. hidraw device ──────────────────────────────────────────────────────────
echo -e "${BOLD}--- hidraw device (LCD) ---${NC}"
HIDRAW_FOUND=false
for dev in /dev/hidraw*; do
    [[ -e "$dev" ]] || continue
    usb_info=$(udevadm info "$dev" 2>/dev/null || true)
    if echo "$usb_info" | grep -q "046d" && \
       echo "$usb_info" | grep -qE "c22d|c22e|c24d|c24e"; then
        ok "hidraw device: $dev  (LCD access)"
        HIDRAW_FOUND=true
    fi
done
$HIDRAW_FOUND || warn "No G510/G510s hidraw device found — LCD may not work"
echo

# ── 4. Input devices ──────────────────────────────────────────────────────────
echo -e "${BOLD}--- Input devices ---${NC}"
INPUT_FOUND=false
for f in /sys/class/input/*/device/name; do
    [[ -f "$f" ]] || continue
    name=$(cat "$f" 2>/dev/null || true)
    if echo "$name" | grep -qi "G510\|G15\|Logitech Gaming"; then
        devdir=$(dirname "$f" | sed 's|/device||')
        eventdev=$(ls "$devdir"/ 2>/dev/null | grep "^event" || true)
        ok "Input: '$name'  →  /dev/input/$eventdev"
        INPUT_FOUND=true
    fi
done
$INPUT_FOUND || warn "No G510/G510s input devices found — G-key events may be unavailable"
echo

# ── 5. G510s-specific: mute LED LEDs via sysfs ────────────────────────────────
if [[ "$DETECTED_MODEL" == "G510s" ]]; then
    echo -e "${BOLD}--- G510s mute LEDs (sysfs) ---${NC}"
    LED_FOUND=false
    for led in /sys/class/leds/*logitech*mute* /sys/class/leds/*g510*mute*; do
        [[ -e "$led" ]] || continue
        ok "Mute LED sysfs: $led"
        LED_FOUND=true
    done
    $LED_FOUND || warn "G510s mute LEDs not exposed via sysfs — USB direct will handle them"
    echo
fi

# ── 6. RGB backlight sysfs LEDs ───────────────────────────────────────────────
echo -e "${BOLD}--- RGB backlight (sysfs) ---${NC}"
RGB_FOUND=false
for pattern in \
    "/sys/class/leds/*logitech*g510*" \
    "/sys/class/leds/*g510*backlight*" \
    "/sys/class/leds/*logitech*kbd*"; do
    for led in $pattern; do
        [[ -e "$led" ]] || continue
        ok "LED: $led"
        RGB_FOUND=true
    done
done
$RGB_FOUND && true || warn "No sysfs RGB LEDs — daemon will use USB direct fallback"
echo

# ── 7. User groups ────────────────────────────────────────────────────────────
echo -e "${BOLD}--- User groups (MOST COMMON CAUSE OF PROBLEMS) ---${NC}"
GROUPS_OUT=$(groups)
MISSING_GROUPS=()
for grp in plugdev input; do
    if echo "$GROUPS_OUT" | grep -qw "$grp"; then
        ok "Member of group: $grp"
    else
        fail "NOT in group: $grp"
        MISSING_GROUPS+=("$grp")
    fi
done
for grp in audio; do
    if echo "$GROUPS_OUT" | grep -qw "$grp"; then
        ok "Member of group: $grp (USB audio)"
    else
        warn "NOT in group '$grp' (only needed for USB audio headset)"
    fi
done
if [ ${#MISSING_GROUPS[@]} -gt 0 ]; then
    echo ""
    echo -e "${RED}  ↳ FIX: Run these commands, then log out and back in:${NC}"
    for grp in "${MISSING_GROUPS[@]}"; do
        echo -e "${RED}        sudo usermod -aG $grp \$USER${NC}"
    done
    echo -e "${YELLOW}  Or apply immediately (this shell only):${NC}"
    for grp in "${MISSING_GROUPS[@]}"; do
        echo -e "${YELLOW}        newgrp $grp${NC}"
    done
    echo ""
fi
echo

# ── 8. Python dependencies ────────────────────────────────────────────────────
echo -e "${BOLD}--- Python dependencies ---${NC}"
for pkg in evdev PIL dbus toml; do
    mod="$pkg"
    [[ "$pkg" == "PIL" ]] && mod="PIL.Image"
    [[ "$pkg" == "toml" ]] && mod="tomllib"
    if python3 -c "import $mod" 2>/dev/null; then
        ok "Python: $pkg"
    else
        warn "Python: $pkg not installed"
    fi
done
for pkg in evdev Pillow pyusb; do
    echo "         pip install $pkg  # if missing"
done
echo

# ── 9. USB audio / ALSA ──────────────────────────────────────────────────────
if [[ "$AUDIO_ACTIVE" == "true" ]]; then
    echo -e "${BOLD}--- USB audio (G510/G510s built-in) ---${NC}"
    if aplay -l 2>/dev/null | grep -qi "G510\|Logitech"; then
        ok "G510 audio visible in ALSA (aplay -l)"
    else
        warn "G510 audio not found via aplay — may need: sudo usermod -aG audio $USER"
    fi
    if amixer -c "$(aplay -l 2>/dev/null | grep -i G510 | awk -F'card ' '{print $2}' | cut -d: -f1 | head -1)" info &>/dev/null 2>&1; then
        ok "ALSA mixer accessible"
    else
        warn "ALSA mixer check skipped (headset may not be plugged in yet)"
    fi
    echo
fi

# ── 10. External tools ─────────────────────────────────────────────────────────
echo -e "${BOLD}--- External tools ---${NC}"
for tool in playerctl pactl xdotool notify-send; do
    if command -v "$tool" &>/dev/null; then
        ok "$tool  ($(command -v $tool))"
    else
        warn "$tool not found — some features won't work"
    fi
done
echo

echo -e "${BOLD}=== Detected: ${DETECTED_MODEL} ===${NC}"
echo "Fix any [FAIL] or [WARN] items above, then: systemctl --user start g510-daemon"
