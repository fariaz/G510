#!/usr/bin/env bash
# install.sh — install g510 stack on Ubuntu/Debian
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BOLD='\033[1m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC}  $*"; }
info() { echo -e "${BOLD}---${NC}  $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }

echo -e "${BOLD}=== G510 Linux stack installer ===${NC}"
echo

# 1. System packages
info "Installing system packages…"
sudo apt-get update -qq
sudo apt-get install -y \
    python3 python3-pip python3-venv \
    python3-gi gir1.2-gtk-3.0 \
    python3-dbus python3-gi-cairo \
    libusb-1.0-0 libusb-dev \
    playerctl pulseaudio-utils \
    xdotool \
    usbutils \
    2>/dev/null && ok "System packages installed"

# 2. Python packages (user-level)
info "Installing Python packages…"
pip3 install --user --quiet evdev Pillow pyusb 2>/dev/null && ok "Python packages installed"

# 3. udev rules
info "Installing udev rules…"
sudo cp udev/99-logitech-g510.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
ok "udev rules installed"

# 4. Add user to groups
info "Adding user to plugdev and input groups…"
sudo usermod -aG plugdev,input "$USER"
warn "You will need to log out and back in for group changes to take effect"

# 5. Install package (daemon + CLI)
info "Installing g510 package…"
if pip3 install --user -e . --quiet 2>/dev/null; then
    ok "Installed via pip (entry_points wired)"
else
    # Fallback: manual copy
    mkdir -p ~/.local/bin
    cp daemon/g510-daemon.py ~/.local/bin/g510-daemon
    cp daemon/g510-ctl.py    ~/.local/bin/g510-ctl
    chmod +x ~/.local/bin/g510-daemon ~/.local/bin/g510-ctl
    PYVER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    SITEPKG=~/.local/lib/python${PYVER}/site-packages
    mkdir -p "$SITEPKG"
    cp -r daemon/g510 "$SITEPKG/"
    warn "Used manual install — 'pip3 install --user -e .' is preferred"
fi
ok "Daemon installed"

# 6. Install GUI
info "Installing GUI…"
cp gui/g510-gui.py ~/.local/bin/g510-gui
chmod +x ~/.local/bin/g510-gui
ok "GUI installed to ~/.local/bin/g510-gui"

# 7. Config + profiles
info "Setting up config…"
mkdir -p ~/.config/g510/profiles ~/.config/g510/macros
if [[ ! -f ~/.config/g510/config.toml ]]; then
    cat > ~/.config/g510/config.toml << 'EOF'
[daemon]
input_device_pattern = "/dev/input/by-id/*Logitech*G510*"
hidraw_device = ""

[lcd]
enabled = true
fps = 4
font_path = ""
font_size = 10
default_screen = "clock"

[rgb]
method = "sysfs"
default_color = [255, 128, 0]

[macros]
scripts_dir = "~/.config/g510/macros"
keystroke_delay_ms = 20

[profiles]
profiles_dir = "~/.config/g510/profiles"
active_profile = "default"
EOF
    ok "Config written to ~/.config/g510/config.toml"
else
    warn "Config already exists — skipping (edit ~/.config/g510/config.toml if needed)"
fi

if [[ ! -f ~/.config/g510/profiles/default.json ]]; then
    cp profiles/default.json ~/.config/g510/profiles/
    ok "Default profile installed"
fi

# 8. systemd user service
info "Installing systemd user service…"
mkdir -p ~/.config/systemd/user
cp systemd/g510-daemon.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable g510-daemon
ok "systemd service enabled"

echo
echo -e "${GREEN}${BOLD}=== Installation complete! ===${NC}"
echo
echo "Next steps:"
echo "  1. Log out and back in (for group membership)"
echo "  2. Run: bash scripts/g510-verify.sh   (check hardware detection)"
echo "  3. Start daemon: systemctl --user start g510-daemon"
echo "  4. Open GUI:     g510-gui"
echo "  5. Check logs:   journalctl --user -u g510-daemon -f"
