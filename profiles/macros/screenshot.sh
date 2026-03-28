#!/usr/bin/env bash
# G510 macro script: take a screenshot and save to ~/Pictures
# Place this in ~/.config/g510/macros/ and mark executable.
# In your profile: { "type": "script", "script": "screenshot.sh" }

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
OUTFILE="$HOME/Pictures/screenshot-$TIMESTAMP.png"

# Try gnome-screenshot, then scrot, then maim
if command -v gnome-screenshot &>/dev/null; then
    gnome-screenshot -f "$OUTFILE"
elif command -v scrot &>/dev/null; then
    scrot "$OUTFILE"
elif command -v maim &>/dev/null; then
    maim "$OUTFILE"
else
    notify-send "G510 macro" "No screenshot tool found (install scrot or maim)"
    exit 1
fi

notify-send "Screenshot saved" "$OUTFILE"
