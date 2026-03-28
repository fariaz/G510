#!/usr/bin/env bash
# build-deb.sh — build g510-daemon and g510-gui .deb packages
#
# Usage:
#   bash build-deb.sh               # build with current version
#   bash build-deb.sh 0.2.0         # build with a new version number
#   bash build-deb.sh --clean       # remove build artefacts only
#
# Requirements (install once):
#   sudo apt install python3 dpkg-dev

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BOLD='\033[1m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC}  $*"; }
info() { echo -e "${BOLD}→${NC}  $*"; }
warn() { echo -e "${YELLOW}!${NC}  $*"; }
die()  { echo -e "${RED}✗${NC}  $*" >&2; exit 1; }

# ── Install build dependencies ────────────────────────────────────────────────
install_build_deps() {
    info "Installing .deb build dependencies..."
    sudo apt-get install -y --no-install-recommends         python3 python3-setuptools         dpkg-dev         gzip         lintian 2>/dev/null || warn "Some build deps could not be installed"
    ok "Build deps ready"
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Subcommand: install build deps ───────────────────────────────────────────
if [[ "${1:-}" == "--install-deps" ]]; then
    install_build_deps
    exit 0
fi

# ── Clean mode ────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--clean" ]]; then
    info "Cleaning build artefacts..."
    rm -rf build/deb
    rm -f ./*.deb
    ok "Clean."
    exit 0
fi

# ── Version handling ──────────────────────────────────────────────────────────
# Read current version from __init__.py
CURRENT_VERSION=$(python3 -c "
import re, sys
text = open('daemon/g510/__init__.py').read()
m = re.search(r'__version__\s*=\s*[\"\']([\w.]+)[\"\']\s*', text)
print(m.group(1) if m else '0.0.0')
")

NEW_VERSION="${1:-$CURRENT_VERSION}"
REVISION="${2:-1}"
PKG_VER="${NEW_VERSION}-${REVISION}"

echo -e "${BOLD}=== g510 .deb builder ===${NC}"
echo "  Version  : $PKG_VER"
echo "  Output   : $(pwd)/*.deb"
echo

# If a new version was given, update source files
if [[ "$NEW_VERSION" != "$CURRENT_VERSION" ]]; then
    info "Updating version: $CURRENT_VERSION → $NEW_VERSION"

    # daemon/g510/__init__.py
    sed -i "s/__version__ = .*/__version__ = \"${NEW_VERSION}\"/" daemon/g510/__init__.py

    # pyproject.toml
    sed -i "s/^version = .*/version = \"${NEW_VERSION}\"/" pyproject.toml

    # setup.py
    sed -i "s/version=\"[^\"]*\"/version=\"${NEW_VERSION}\"/" setup.py 2>/dev/null || true

    # debian/changelog — prepend a new entry
    DATESTAMP=$(date -R)
    TMPFILE=$(mktemp)
    cat > "$TMPFILE" << ENTRY
g510 (${PKG_VER}) noble; urgency=medium

  * Release ${NEW_VERSION}.

 -- Fariaz <fariaz@users.noreply.github.com>  ${DATESTAMP}

ENTRY
    cat debian/changelog >> "$TMPFILE"
    mv "$TMPFILE" debian/changelog

    # Man page dates
    TODAY=$(date +%Y-%m-%d)
    sed -i "s/\"[0-9-]*\"/\"${TODAY}\"/" debian/g510-daemon.1 debian/g510-ctl.1 2>/dev/null || true

    ok "Version updated to $NEW_VERSION"
fi

# ── Build ──────────────────────────────────────────────────────────────────────
# Remove all existing .deb files so output is unambiguous
rm -f ./*.deb 2>/dev/null || true

info "Building packages..."
python3 - << PYEOF
import hashlib, os, shutil, subprocess, stat
from pathlib import Path

VERSION  = "${NEW_VERSION}"
REVISION = "${REVISION}"
PKG_VER  = f"{VERSION}-{REVISION}"
ARCH     = "all"
SITEPKG  = "usr/lib/python3/dist-packages"

ROOT  = Path(".").resolve()
BUILD = ROOT / "build" / "deb"
shutil.rmtree(BUILD, ignore_errors=True)

def mkdir(p): Path(p).mkdir(parents=True, exist_ok=True)
def cp(src, dst): shutil.copy2(src, dst)
def cptree(src, dst):
    shutil.copytree(src, dst, dirs_exist_ok=True,
        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))

def fix_shebang(path: Path):
    text = path.read_text()
    lines = text.splitlines()
    if lines and lines[0].startswith('#!'):
        lines[0] = '#!/usr/bin/python3'
    else:
        lines.insert(0, '#!/usr/bin/python3')
    path.write_text('\n'.join(lines) + '\n')
    path.chmod(0o755)

def write_md5sums(pkg_dir: Path):
    sums = []
    for f in sorted(pkg_dir.rglob('*')):
        if 'DEBIAN' in f.parts or not f.is_file():
            continue
        rel = f.relative_to(pkg_dir)
        md5 = hashlib.md5(f.read_bytes()).hexdigest()
        sums.append(f'{md5}  {rel}')
    (pkg_dir / 'DEBIAN' / 'md5sums').write_text('\n'.join(sums) + '\n')

def add_installed_size(ctrl: Path, pkg_dir: Path):
    total = sum(f.stat().st_size for f in pkg_dir.rglob('*')
                if f.is_file() and 'DEBIAN' not in f.parts)
    text = ctrl.read_text()
    if 'Installed-Size:' not in text:
        ctrl.write_text(text + f'Installed-Size: {total // 1024 + 1}\n')

def build_pkg(pkg_dir: Path, out_deb: Path):
    add_installed_size(pkg_dir / 'DEBIAN' / 'control', pkg_dir)
    write_md5sums(pkg_dir)
    r = subprocess.run(
        ['dpkg-deb', '--build', '--root-owner-group', str(pkg_dir), str(out_deb)],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        print(r.stderr)
        raise RuntimeError(f"dpkg-deb failed for {out_deb.name}")
    kb = out_deb.stat().st_size // 1024
    print(f"  {out_deb.name}  ({kb} KB)")

# ── g510-daemon ──────────────────────────────────────────────────────────────
D = BUILD / f"g510-daemon_{PKG_VER}_{ARCH}"
CTRL = D / "DEBIAN"
mkdir(CTRL)

(CTRL / "control").write_text(
    f"Package: g510-daemon\n"
    f"Version: {PKG_VER}\n"
    f"Architecture: {ARCH}\n"
    f"Maintainer: Fariaz <fariaz@users.noreply.github.com>\n"
    f"Depends: python3 (>= 3.11), python3-evdev, python3-pil, adduser\n"
    f"Recommends: python3-usb, python3-gi, python3-dbus,"
    f" playerctl, pulseaudio-utils, xdotool\n"
    f"Suggests: g510-gui\n"
    f"Section: utils\n"
    f"Priority: optional\n"
    f"Homepage: https://github.com/fariaz/g510\n"
    f"Description: Logitech G510/G510s keyboard daemon for Linux\n"
    f" Userspace driver daemon for the Logitech G510 and G510s gaming keyboards.\n"
    f" Provides G1-G18 macros, RGB backlight, LCD GamePanel, MR record mode,\n"
    f" media keys, volume wheel, D-Bus interface, and JSON profiles.\n"
    f" Requires the hid-lg-g15 kernel module (mainline since Linux 5.5).\n"
)
for s in ['postinst', 'postrm']:
    dst = CTRL / s
    shutil.copy2(ROOT / 'debian' / f'g510-daemon.{s}', dst)
    dst.chmod(0o755)
(CTRL / 'conffiles').write_text('/etc/udev/rules.d/99-logitech-g510.rules\n')

cptree(ROOT / 'daemon' / 'g510', D / SITEPKG / 'g510')
bindir = D / 'usr' / 'bin'; mkdir(bindir)
for src_rel, name in [('daemon/g510-daemon.py','g510-daemon'),('daemon/g510-ctl.py','g510-ctl')]:
    dst = bindir / name; shutil.copy2(ROOT / src_rel, dst); fix_shebang(dst)
verify = bindir / 'g510-verify'
verify.write_text('#!/bin/sh\nexec /usr/share/g510/g510-verify.sh "\$@"\n')
verify.chmod(0o755)

udev_dst = D / 'etc' / 'udev' / 'rules.d'; mkdir(udev_dst)
shutil.copy2(ROOT / 'udev' / '99-logitech-g510.rules', udev_dst)

sys_dst = D / 'usr' / 'lib' / 'systemd' / 'user'; mkdir(sys_dst)
shutil.copy2(ROOT / 'systemd' / 'g510-daemon.service', sys_dst)

# XDG autostart (for non-systemd GNOME/KDE desktops)
xdg_dst = D / 'etc' / 'xdg' / 'autostart'; mkdir(xdg_dst)
shutil.copy2(ROOT / 'debian' / 'g510-daemon-autostart.desktop', xdg_dst)

share = D / 'usr' / 'share' / 'g510'
mkdir(share / 'profiles'); mkdir(share / 'macros')
shutil.copy2(ROOT / 'profiles' / 'default.json', share / 'profiles')
for sh in (ROOT / 'profiles' / 'macros').glob('*.sh'):
    out = share / 'macros' / sh.name; shutil.copy2(sh, out); out.chmod(0o755)
shutil.copy2(ROOT / 'scripts' / 'g510-verify.sh', share / 'g510-verify.sh')
(share / 'g510-verify.sh').chmod(0o755)

man1 = D / 'usr' / 'share' / 'man' / 'man1'; mkdir(man1)
for m in ['g510-daemon.1', 'g510-ctl.1']:
    shutil.copy2(ROOT / 'debian' / m, man1 / m)
    subprocess.run(['gzip','-9','-f', str(man1/m)], check=True, capture_output=True)

doc = D / 'usr' / 'share' / 'doc' / 'g510-daemon'; mkdir(doc)
shutil.copy2(ROOT / 'README.md', doc)
shutil.copy2(ROOT / 'CHANGELOG.md', doc)
subprocess.run(['gzip','-9','-f', str(doc/'CHANGELOG.md')], check=True, capture_output=True)
shutil.copy2(ROOT / 'debian' / 'copyright', doc)

build_pkg(D, ROOT / f"g510-daemon_{PKG_VER}_{ARCH}.deb")

# ── g510-gui ─────────────────────────────────────────────────────────────────
G = BUILD / f"g510-gui_{PKG_VER}_{ARCH}"
CTRL2 = G / "DEBIAN"; mkdir(CTRL2)
(CTRL2 / 'control').write_text(
    f"Package: g510-gui\n"
    f"Version: {PKG_VER}\n"
    f"Architecture: {ARCH}\n"
    f"Maintainer: Fariaz <fariaz@users.noreply.github.com>\n"
    f"Depends: g510-daemon (= {PKG_VER}), python3 (>= 3.11), python3-gi,"
    f" gir1.2-gtk-3.0, python3-dbus\n"
    f"Section: utils\n"
    f"Priority: optional\n"
    f"Homepage: https://github.com/fariaz/g510\n"
    f"Description: GTK3 control panel for the Logitech G510/G510s keyboard\n"
    f" Graphical configuration tool for the G510/G510s keyboard daemon.\n"
    f" Designed for LXQt and other X11 desktop environments.\n"
    f" Provides a macro editor, RGB colour picker, LCD screen selector,\n"
    f" profile manager, and live bank indicator.\n"
)
bin2 = G / 'usr' / 'bin'; mkdir(bin2)
dst2 = bin2 / 'g510-gui'; shutil.copy2(ROOT / 'gui' / 'g510-gui.py', dst2); fix_shebang(dst2)
apps = G / 'usr' / 'share' / 'applications'; mkdir(apps)
shutil.copy2(ROOT / 'debian' / 'g510-gui.desktop', apps)
man1g = G / 'usr' / 'share' / 'man' / 'man1'; mkdir(man1g)
(man1g / 'g510-gui.1').write_text(
    '.TH G510-GUI 1 "2026-03-28" "g510" "User Commands"\n'
    '.SH NAME\ng510-gui \\- GTK3 control panel for the Logitech G510/G510s keyboard (LXQt/X11)\n'
    '.SH SYNOPSIS\n.B g510-gui\n'
    '.SH DESCRIPTION\nGraphical configuration tool for g510-daemon.\n'
    '.SH SEE ALSO\n.BR g510-daemon (1),\n.BR g510-ctl (1)\n'
)
subprocess.run(['gzip','-9','-f', str(man1g/'g510-gui.1')], check=True, capture_output=True)
doc2 = G / 'usr' / 'share' / 'doc' / 'g510-gui'; mkdir(doc2)
shutil.copy2(ROOT / 'debian' / 'copyright', doc2)
build_pkg(G, ROOT / f"g510-gui_{PKG_VER}_{ARCH}.deb")
PYEOF

# ── Verification ──────────────────────────────────────────────────────────────
echo
info "Verifying packages..."

# Structural check
for deb in g510-daemon_${PKG_VER}_all.deb g510-gui_${PKG_VER}_all.deb; do
    if [[ -f "$deb" ]]; then
        # Verify all files are readable and metadata is complete
        if dpkg-deb --info "$deb" >/dev/null 2>&1 && dpkg-deb -c "$deb" >/dev/null 2>&1; then
            ok "$deb  — structure OK"
        else
            warn "$deb  — structure check failed"
        fi
        # Check for __pycache__ accidentally included
        if dpkg-deb -c "$deb" 2>/dev/null | grep -q __pycache__; then
            warn "$deb contains __pycache__ (should not)"
        fi
    fi
done

# Simulate install (dry run) — catches dependency issues
if command -v dpkg >/dev/null 2>&1; then
    for deb in g510-daemon_${PKG_VER}_all.deb g510-gui_${PKG_VER}_all.deb; do
        [[ -f "$deb" ]] || continue
        if dpkg --dry-run -i "$deb" 2>/dev/null; then
            ok "$deb  — dpkg dry-run OK"
        else
            # Not necessarily an error — may just mean deps not installed
            warn "$deb  — dpkg dry-run had warnings (normal if deps not installed)"
        fi
    done
fi 2>/dev/null || true

# Run lintian if available
if command -v lintian >/dev/null 2>&1; then
    info "Running lintian..."
    for deb in g510-daemon_${PKG_VER}_all.deb g510-gui_${PKG_VER}_all.deb; do
        [[ -f "$deb" ]] || continue
        LINTIAN_OUT=$(lintian --no-tag-display-limit "$deb" 2>&1) || true
        # Filter known-safe warnings
        FILTERED=$(echo "$LINTIAN_OUT" | grep -v "^I:" | grep -v "^N:" || true)
        if [[ -z "$FILTERED" ]]; then
            ok "$deb  — lintian clean"
        else
            warn "$deb lintian output:"
            echo "$FILTERED" | sed 's/^/     /'
        fi
    done
else
    warn "lintian not installed — skipping lint check (install with: sudo apt install lintian)"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo
ok "Build complete:"
for deb in ./*.deb; do
    size=$(du -sh "$deb" | cut -f1)
    echo "     $deb  ($size)"
done
echo
echo -e "${BOLD}Install with:${NC}"
echo "  sudo dpkg -i g510-daemon_${PKG_VER}_all.deb g510-gui_${PKG_VER}_all.deb"
echo "  sudo apt-get install -f   # fix any missing dependencies"
