#!/usr/bin/env bash
# G510 macro script: toggle microphone mute and show OSD
pactl set-source-mute @DEFAULT_SOURCE@ toggle

# Check new state
MUTED=$(pactl get-source-mute @DEFAULT_SOURCE@ | grep -c "yes")
if [ "$MUTED" -eq 1 ]; then
    notify-send -i microphone-sensitivity-muted "Microphone MUTED" ""
else
    notify-send -i microphone-sensitivity-high "Microphone ACTIVE" ""
fi
