#!/usr/bin/env bash
# G510 macro: show system info as a desktop notification

CPU=$(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | cut -d. -f1)
MEM_USED=$(free -h | awk '/^Mem:/ {print $3}')
MEM_TOTAL=$(free -h | awk '/^Mem:/ {print $2}')
DISK=$(df -h / | awk 'NR==2 {print $3 "/" $2 " (" $5 ")"}')
UPTIME=$(uptime -p | sed 's/up //')

notify-send "System Info" \
    "CPU: ${CPU}%\nMem: ${MEM_USED} / ${MEM_TOTAL}\nDisk: ${DISK}\nUptime: ${UPTIME}"
