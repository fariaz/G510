# Makefile — g510-linux development helpers
# Usage: make <target>

.PHONY: help install install-deps test lint fmt verify start stop restart logs \
        package clean daemon-debug gui ctl-status

DAEMON   = daemon/g510-daemon.py
CTL      = daemon/g510-ctl.py
GUI      = gui/g510-gui.py
VERIFY   = scripts/g510-verify.sh
PYPATH   = PYTHONPATH=daemon

# ─── Help ─────────────────────────────────────────────────────────────────────
help:
	@echo "g510-linux — Logitech G510 Linux driver stack"
	@echo ""
	@echo "Setup:"
	@echo "  make install        Full install (udev + daemon + GUI + service)"
	@echo "  make install-deps   Install Python + system dependencies only"
	@echo "  make verify         Check hardware detection and kernel module"
	@echo ""
	@echo "Development:"
	@echo "  make daemon-debug   Run daemon in foreground with verbose logging"
	@echo "  make gui            Launch the GUI control panel"
	@echo "  make ctl-status     Show daemon status via g510-ctl"
	@echo ""
	@echo "Service management:"
	@echo "  make start          Start the systemd user service"
	@echo "  make stop           Stop the systemd user service"
	@echo "  make restart        Restart the systemd user service"
	@echo "  make logs           Follow daemon logs"
	@echo ""
	@echo "Testing:"
	@echo "  make test           Run all tests"
	@echo "  make lint           Run flake8 linter"
	@echo "  make fmt            Auto-format with black"
	@echo ""
	@echo "Packaging:"
	@echo "  make deb            Build .deb packages"
	@echo "  make deb-version    Bump version and build .deb"
	@echo "  make deb-clean      Remove .deb build artefacts"
	@echo "  make deb-deps       Install .deb build dependencies"
	@echo "  make package        Build release tarball"
	@echo "  make clean          Remove build artefacts"

# ─── Setup ────────────────────────────────────────────────────────────────────
install-deps:
	sudo apt-get install -y \
	    python3 python3-pip \
	    python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 \
	    python3-dbus python3-gi-cairo \
	    libusb-1.0-0 playerctl pulseaudio-utils xdotool usbutils
	pip3 install --user --quiet evdev Pillow pyusb

install: install-deps
	@bash install.sh

verify:
	@bash $(VERIFY)

# ─── Development ──────────────────────────────────────────────────────────────
daemon-debug:
	$(PYPATH) python3 $(DAEMON) --verbose

gui:
	$(PYPATH) python3 $(GUI)

ctl-status:
	$(PYPATH) python3 $(CTL) status

# ─── Service management ───────────────────────────────────────────────────────
start:
	systemctl --user start g510-daemon
	@echo "Started. Logs: make logs"

stop:
	systemctl --user stop g510-daemon

restart:
	systemctl --user restart g510-daemon
	@echo "Restarted. Logs: make logs"

logs:
	journalctl --user -u g510-daemon -f --output=short-monotonic

# ─── Testing ──────────────────────────────────────────────────────────────────
test:
	$(PYPATH) python3 -m pytest tests/ -v --tb=short 2>/dev/null || \
	$(PYPATH) python3 -c "\
import subprocess, sys; \
r = subprocess.run([sys.executable, 'tests/run_tests.py'], cwd='.'); \
sys.exit(r.returncode)"

test-fast:
	$(PYPATH) python3 -m pytest tests/ -x -q 2>/dev/null

lint:
	@command -v flake8 >/dev/null 2>&1 || pip3 install --user --quiet flake8
	flake8 daemon/g510/ gui/ --max-line-length=100 \
	    --extend-ignore=E501,W503,E203 \
	    --exclude=__pycache__

fmt:
	@command -v black >/dev/null 2>&1 || pip3 install --user --quiet black
	black daemon/g510/ daemon/g510-*.py gui/ tests/ --line-length=100

# ─── Packaging ────────────────────────────────────────────────────────────────
VERSION  = $(shell grep '__version__' daemon/g510/__init__.py | cut -d'"' -f2)
TARBALL  = g510-linux-$(VERSION).tar.gz

deb:
	@bash build-deb.sh

deb-version:
	@read -p "New version (current: $(VERSION)): " v; bash build-deb.sh $$v

deb-clean:
	@bash build-deb.sh --clean

deb-deps:
	@bash build-deb.sh --install-deps

package:
	@echo "Building $(TARBALL)..."
	tar czf $(TARBALL) \
	    --exclude='*/__pycache__' \
	    --exclude='*.pyc' \
	    --exclude='.git' \
	    --exclude='*.tar.gz' \
	    --exclude='*.deb' \
	    --exclude='build/' \
	    --transform='s|^\.|g510-linux-$(VERSION)|' \
	    .
	@echo "Created: $(TARBALL) ($$(du -sh $(TARBALL) | cut -f1))"

clean:
	find . -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null; true
	find . -name '*.pyc' -delete 2>/dev/null; true
	rm -f *.tar.gz
	@echo "Clean."
