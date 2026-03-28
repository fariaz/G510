"""
g510.lcd — GamePanel LCD manager (160 × 43 pixels, monochrome).

Renders frames using Pillow and sends them to the G510's hidraw device.
Built-in screens: clock, system info, custom (via profile).
"""

import glob
import logging
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    logging.warning("Pillow not installed — LCD disabled. pip install Pillow")

log = logging.getLogger(__name__)

LCD_WIDTH  = 160
LCD_HEIGHT = 43


def _encode_and_send(hidraw_path: str, img: "Image.Image") -> bool:
    """Encode a PIL Image to G510 wire format and write to hidraw."""
    from g510.lcd_wire import frame_from_pil, send_frame
    reports = frame_from_pil(img)
    return send_frame(hidraw_path, reports)


class LCDScreen:
    """Base class for LCD screens."""
    name = "base"

    def render(self) -> "Image.Image":
        img = Image.new("1", (LCD_WIDTH, LCD_HEIGHT), 1)  # white bg
        return img


class ClockScreen(LCDScreen):
    name = "clock"

    def __init__(self, font=None, font_small=None):
        self.font       = font
        self.font_small = font_small

    def render(self) -> "Image.Image":
        img  = Image.new("1", (LCD_WIDTH, LCD_HEIGHT), 1)
        draw = ImageDraw.Draw(img)
        now  = datetime.now()

        time_str = now.strftime("%H:%M:%S")
        date_str = now.strftime("%a %d %b %Y")

        # Time — large, centred
        draw.text((LCD_WIDTH // 2, 8), time_str,
                  font=self.font, fill=0, anchor="mm")
        # Date — small, below
        draw.text((LCD_WIDTH // 2, 32), date_str,
                  font=self.font_small, fill=0, anchor="mm")
        return img


class SysInfoScreen(LCDScreen):
    name = "sysinfo"

    def __init__(self, font_small=None):
        self.font = font_small
        # Delta tracking for accurate CPU measurement
        self._prev_total: int = 0
        self._prev_idle:  int = 0
        self._cpu_cache:  float = 0.0

    def render(self) -> "Image.Image":
        img  = Image.new("1", (LCD_WIDTH, LCD_HEIGHT), 1)
        draw = ImageDraw.Draw(img)

        cpu = self._cpu_percent()
        mem = self._mem_percent()

        draw.text((2, 2),  f"CPU: {cpu:5.1f}%", font=self.font, fill=0)
        draw.text((2, 14), f"MEM: {mem:5.1f}%", font=self.font, fill=0)
        draw.text((2, 26), datetime.now().strftime("%H:%M:%S"), font=self.font, fill=0)

        # CPU bar graph
        bar_w = max(0, int((LCD_WIDTH - 4) * cpu / 100))
        draw.rectangle([2, 36, LCD_WIDTH - 2, 41], outline=0)
        if bar_w > 0:
            draw.rectangle([2, 36, 2 + bar_w, 41], fill=0)

        return img

    def _cpu_percent(self) -> float:
        """Accurate CPU% using delta between two reads (avoids single-sample error)."""
        try:
            with open("/proc/stat") as f:
                line = f.readline().split()
            vals  = [int(x) for x in line[1:8]]  # user nice system idle iowait irq softirq
            total = sum(vals)
            idle  = vals[3] + vals[4]  # idle + iowait

            delta_total = total - self._prev_total
            delta_idle  = idle  - self._prev_idle
            self._prev_total = total
            self._prev_idle  = idle

            if delta_total == 0:
                return self._cpu_cache
            self._cpu_cache = max(0.0, 100.0 * (1.0 - delta_idle / delta_total))
            return self._cpu_cache
        except Exception:
            return 0.0

    @staticmethod
    def _mem_percent() -> float:
        try:
            info = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    k, v = line.split(":")
                    info[k.strip()] = int(v.split()[0])
            total = info.get("MemTotal", 1)
            avail = info.get("MemAvailable", total)
            return 100.0 * (1 - avail / total)
        except Exception:
            return 0.0


class NowPlayingScreen(LCDScreen):
    """Show currently playing media via playerctl."""
    name = "nowplaying"

    def __init__(self, font=None, font_small=None):
        self.font    = font
        self.font_sm = font_small
        self._cache  = ("", "", 0.0)   # (artist, title, position_fraction)
        self._last_update = 0.0
        self._UPDATE_INTERVAL = 2.0    # poll playerctl every 2s
        self._scroll_start = time.monotonic()  # when current title scroll began
        self._scroll_title = ""               # title the scroll was calibrated for
        self._scroll_px_per_s = 20           # pixels per second scroll speed

    def render(self) -> "Image.Image":
        img  = Image.new("1", (LCD_WIDTH, LCD_HEIGHT), 1)
        draw = ImageDraw.Draw(img)

        now = time.monotonic()
        if now - self._last_update > self._UPDATE_INTERVAL:
            self._cache = self._poll_playerctl()
            self._last_update = now

        artist, title, pos = self._cache

        if not title:
            draw.text((LCD_WIDTH // 2, LCD_HEIGHT // 2), "Nothing playing",
                      font=self.font_sm, fill=0, anchor="mm")
            return img

        # Smooth continuous scroll — reset when title changes
        if title != self._scroll_title:
            self._scroll_title = title
            self._scroll_start = now
        title_px = max(1, len(title) * 7)
        elapsed  = now - self._scroll_start
        # Scroll left then pause at end before looping
        cycle    = title_px + LCD_WIDTH   # total scroll distance per loop
        scroll_offset = int(elapsed * self._scroll_px_per_s) % cycle
        # Clamp so text exits fully before looping
        draw.text((2 - scroll_offset, 4), title, font=self.font, fill=0)

        # Artist underneath
        artist_trunc = artist[:22] if artist else ""
        draw.text((2, 20), artist_trunc, font=self.font_sm, fill=0)

        # Progress bar
        bar_w = int((LCD_WIDTH - 4) * max(0.0, min(1.0, pos)))
        draw.rectangle([2, 35, LCD_WIDTH - 2, 41], outline=0)
        if bar_w > 0:
            draw.rectangle([2, 35, 2 + bar_w, 41], fill=0)

        return img

    @staticmethod
    def _poll_playerctl() -> tuple:
        import subprocess
        def run(args):
            try:
                return subprocess.check_output(
                    ["playerctl"] + args, stderr=subprocess.DEVNULL,
                    timeout=1
                ).decode().strip()
            except Exception:
                return ""

        status = run(["status"])
        if status not in ("Playing", "Paused"):
            return ("", "", 0.0)

        artist   = run(["metadata", "artist"])
        title    = run(["metadata", "title"])
        pos_str  = run(["metadata", "mpris:length"])   # microseconds
        pos_now  = run(["position"])                    # seconds (float)

        try:
            length_us = int(pos_str)
            pos_sec   = float(pos_now)
            fraction  = pos_sec / (length_us / 1_000_000) if length_us else 0.0
        except (ValueError, ZeroDivisionError):
            fraction = 0.0

        return (artist, title, fraction)


class BankFlashScreen(LCDScreen):
    """Briefly shows which M-bank just became active, then reverts."""
    name = "bankflash"

    def __init__(self, bank: str, font=None):
        self.bank  = bank
        self.font  = font
        self.born  = time.monotonic()
        self.ttl   = 1.5   # seconds to display

    def expired(self) -> bool:
        return time.monotonic() - self.born > self.ttl

    def render(self) -> "Image.Image":
        img  = Image.new("1", (LCD_WIDTH, LCD_HEIGHT), 1)
        draw = ImageDraw.Draw(img)
        # Big bank indicator centred
        draw.text((LCD_WIDTH // 2, LCD_HEIGHT // 2), self.bank,
                  font=self.font, fill=0, anchor="mm")
        # Thin border
        draw.rectangle([0, 0, LCD_WIDTH - 1, LCD_HEIGHT - 1], outline=0)
        return img


class CustomScreen(LCDScreen):
    """Render arbitrary text lines from profile config."""
    name = "custom"

    def __init__(self, lines: list[str], font=None):
        self.lines = lines
        self.font  = font

    def render(self) -> "Image.Image":
        img  = Image.new("1", (LCD_WIDTH, LCD_HEIGHT), 1)
        draw = ImageDraw.Draw(img)
        y = 2
        for line in self.lines[:5]:
            draw.text((2, y), line, font=self.font, fill=0)
            y += 8
        return img


class LCDManager:
    def __init__(self, config, profile=None):
        self._cfg     = config.lcd
        self._hidraw  = self._find_hidraw(config.hidraw_device)
        self._thread  = None
        self._running = False
        self._lock    = threading.Lock()
        self._screen  = None
        self._font    = None
        self._font_sm = None
        self._load_fonts()
        self._init_screens(profile)

    def _find_hidraw(self, hint: str) -> Optional[str]:
        if hint:
            return hint
        # Auto-detect: find hidraw device belonging to G510
        for dev in glob.glob("/dev/hidraw*"):
            try:
                import subprocess
                out = subprocess.check_output(
                    ["udevadm", "info", dev], stderr=subprocess.DEVNULL
                ).decode()
                if "046d" in out and ("c22d" in out or "c22e" in out):
                    log.info("Auto-detected hidraw: %s", dev)
                    return dev
            except Exception:
                pass
        log.warning("No hidraw device found — LCD disabled")
        return None

    def _load_fonts(self):
        if not HAS_PIL:
            return
        try:
            font_path = self._cfg.font_path
            size = self._cfg.font_size
            if font_path and Path(font_path).exists():
                self._font    = ImageFont.truetype(font_path, size + 4)
                self._font_sm = ImageFont.truetype(font_path, size)
            else:
                # Try common system fonts
                for fp in ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                           "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"]:
                    if Path(fp).exists():
                        self._font    = ImageFont.truetype(fp, size + 4)
                        self._font_sm = ImageFont.truetype(fp, size)
                        break
        except Exception as e:
            log.debug("Font load failed: %s — using default", e)

    def _init_screens(self, profile=None):
        # Prefer screen saved in active profile, fall back to config default
        if profile and profile.lcd.get("screen"):
            default = profile.lcd["screen"]
        else:
            default = self._cfg.default_screen
        screens = {
            "clock":      ClockScreen(self._font, self._font_sm),
            "sysinfo":    SysInfoScreen(self._font_sm),
            "nowplaying": NowPlayingScreen(self._font, self._font_sm),
        }
        self._screen = screens.get(default, screens["clock"])
        log.debug("LCD screen restored to: %s", default)

    def set_screen(self, name: str, _profile_mgr=None, **kwargs):
        """Switch active screen. If _profile_mgr is provided, persists the choice."""
        with self._lock:
            if name == "clock":
                self._screen = ClockScreen(self._font, self._font_sm)
            elif name == "sysinfo":
                self._screen = SysInfoScreen(self._font_sm)
            elif name == "nowplaying":
                self._screen = NowPlayingScreen(self._font, self._font_sm)
            elif name == "custom":
                self._screen = CustomScreen(kwargs.get("lines", []), self._font_sm)
            else:
                log.warning("Unknown screen: %s", name)
                return
        # Persist to profile so the choice survives daemon restart
        if _profile_mgr is not None:
            try:
                _profile_mgr.active._data.setdefault("lcd", {})["screen"] = name
                _profile_mgr.save_active()
            except Exception as e:
                log.debug("Failed to persist LCD screen: %s", e)

    def notify_bank_change(self, bank: str):
        """Flash the bank name on the LCD for 1.5s, then restore previous screen."""
        with self._lock:
            prev  = self._screen
            flash = BankFlashScreen(bank, self._font)
            self._screen = flash

        def _restore():
            # Poll until the flash screen has expired, then restore
            while not flash.expired():
                time.sleep(0.05)
            with self._lock:
                if self._screen is flash:   # don't clobber a manual change
                    self._screen = prev
        threading.Thread(target=_restore, daemon=True).start()

    def _send_frame(self, img: "Image.Image"):
        if not self._hidraw or not HAS_PIL:
            return
        ok = _encode_and_send(self._hidraw, img)
        if not ok:
            log.debug("LCD write failed for %s", self._hidraw)

    def _render_loop(self):
        interval = 1.0 / max(1, self._cfg.fps)
        while self._running:
            t0 = time.monotonic()
            with self._lock:
                screen = self._screen
            if screen and HAS_PIL:
                try:
                    img = screen.render()
                    self._send_frame(img)
                except Exception as e:
                    log.error("LCD render error: %s", e)
            elapsed = time.monotonic() - t0
            time.sleep(max(0, interval - elapsed))

    def start(self):
        if not HAS_PIL:
            log.warning("Pillow not installed — LCD thread not started")
            return
        self._running = True
        self._thread = threading.Thread(target=self._render_loop, daemon=True)
        self._thread.start()
        log.info("LCD manager started (screen=%s, fps=%d)", self._cfg.default_screen, self._cfg.fps)

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
