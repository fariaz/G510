# Publishing to GitHub

Step-by-step guide to publish this project to **https://github.com/fariaz/g510**.

---

## Prerequisites

```bash
# Install git if needed
sudo apt install git

# Configure your identity (once ever)
git config --global user.name  "fariaz"
git config --global user.email "fariaz@users.noreply.github.com"
```

---

## Step 1 — Create the GitHub repository

1. Go to https://github.com/new
2. Fill in:
   - **Repository name**: `g510`
   - **Description**: `Full Linux driver stack for the Logitech G510 / G510s keyboard`
   - **Visibility**: Public
   - **Do NOT** initialise with README, .gitignore, or licence (we have all of these)
3. Click **Create repository**

---

## Step 2 — Initialise and push

Run these commands from the project root (the directory containing `README.md`):

```bash
cd /path/to/g510-linux

# Initialise git repo
git init
git branch -M main

# Stage everything
git add -A

# First commit
git commit -m "chore: initial release v0.1.0

Full Linux userspace driver for the Logitech G510 and G510s keyboard.

Features:
- G1-G18 macro keys with M1/M2/M3 bank switching
- MR on-the-fly macro recording
- RGB backlight control (sysfs + USB HID)
- LCD GamePanel (clock, sysinfo, now-playing, custom)
- Media keys, volume wheel, mute/mic-mute
- G510s: headphone/mic mute LEDs, game-mode key
- GTK3 GUI for LXQt/X11
- D-Bus interface (org.g510.Daemon)
- JSON profiles, .deb packaging"

# Connect to GitHub
git remote add origin https://github.com/fariaz/g510.git

# Push
git push -u origin main
```

---

## Step 3 — Tag the first release

```bash
git tag -a v0.1.0 -m "Release v0.1.0 — initial public release"
git push origin v0.1.0
```

This triggers the CI workflow which will:
1. Run all 55 tests on Python 3.11 and 3.12
2. Build `g510-daemon_0.1.0-1_all.deb` and `g510-gui_0.1.0-1_all.deb`
3. Create a GitHub Release at https://github.com/fariaz/g510/releases with the `.deb` files attached

---

## Step 4 — Verify CI

Go to https://github.com/fariaz/g510/actions and confirm:
- ✅ `Test (Python 3.11)` — passed
- ✅ `Test (Python 3.12)` — passed
- ✅ `Build .deb packages` — passed
- ✅ `Create GitHub Release` — passed (only runs on tags)

The CI status badge in the README will turn green automatically.

---

## Releasing a new version

```bash
# 1. Bump version and build .deb (updates __init__.py, pyproject.toml, debian/changelog)
bash build-deb.sh 0.2.0

# 2. Commit
git add -A
git commit -m "chore: release v0.2.0"

# 3. Tag — this triggers the GitHub Release workflow
git tag -a v0.2.0 -m "Release v0.2.0"
git push && git push origin v0.2.0
```

---

## Repository structure reference

```
g510/
├── .github/workflows/ci.yml   # CI: test → build .deb → release on tag
├── .gitignore
├── LICENSE                    # MIT
├── README.md                  # ← badges auto-update after CI runs
├── CHANGELOG.md
├── CONTRIBUTING.md
├── Makefile                   # make deb / make test / make lint
├── build-deb.sh               # build .deb packages (no debhelper needed)
├── install.sh                 # source install for non-.deb users
├── pyproject.toml             # Python packaging (pip install -e .)
├── daemon/
│   ├── g510-daemon.py         # main daemon entry point
│   ├── g510-ctl.py            # CLI tool
│   └── g510/                  # Python package
│       ├── config.py
│       ├── keyboard.py        # evdev input, hotplug
│       ├── macros.py          # macro engine (xdotool for text)
│       ├── lcd.py             # LCD GamePanel renderer
│       ├── rgb.py             # RGB backlight (sysfs + USB HID)
│       ├── profiles.py        # JSON profiles
│       ├── model.py           # G510 vs G510s detection
│       ├── dbus_iface.py      # org.g510.Daemon D-Bus service
│       └── macrorec.py        # MR record FSM
├── gui/
│   └── g510-gui.py            # GTK3 control panel (LXQt/X11)
├── debian/                    # .deb packaging (dpkg-buildpackage compatible)
├── udev/                      # 99-logitech-g510.rules (all 4 PIDs)
├── systemd/                   # g510-daemon.service (user unit)
├── profiles/                  # example profile JSON + macro scripts
├── scripts/
│   ├── g510-verify.sh         # hardware detection + setup check
│   └── set-repo.sh            # re-run to change GitHub username/email
└── tests/                     # 55 tests, no hardware required
```

---

## Useful GitHub settings to configure after publish

- **Settings → General → Features**: enable Issues, disable Wiki (use README)
- **Settings → Branches**: add branch protection rule on `main` (require CI to pass)
- **Settings → Pages**: disable (not needed)
- **About** (top-right of repo): set description and add topics:
  `logitech`, `g510`, `keyboard`, `linux`, `gaming`, `macro`, `lcd`, `gtk3`, `lxqt`, `ubuntu`
