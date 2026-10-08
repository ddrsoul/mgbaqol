# SPDX-License-Identifier: GPL-2.0-or-later
"""What every game's companion shares: the window on the bottom screen, the
drawing primitives, the tab bar, touch and right-stick input, and the main loop.

A game's App subclasses BaseApp and provides TABS / VIEWS, load_game(),
draw_view(), stick_view() and tap_view(); see main.py (Pokemon), fe.py, aw.py.
"""

import ctypes
import os
import queue
import struct
import subprocess
import threading
import time

import sdl
from stick import RightStick
from theme import *  # noqa: F401,F403 - geometry, font, colours

RA_APP_ID = "com.libretro.RetroArch"


def log(msg):
    print("[mgbaqol] %s" % msg, flush=True)


def swaymsg(*args):
    try:
        return subprocess.run(["swaymsg", *args], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def retroarch_running(pid):
    if pid:
        return os.path.exists("/proc/%d" % pid)
    for entry in os.listdir("/proc"):
        if entry.isdigit():
            try:
                with open("/proc/%s/cmdline" % entry, "rb") as f:
                    if b"retroarch" in f.read().split(b"\0")[0]:
                        return True
            except OSError:
                pass
    return False


def dim(c, k=4):
    return tuple(v // k for v in c)


class BaseApp:
    TABS = []                  # labels in the tab bar
    VIEWS = []                 # one per tab, plus "settings" for the menu button

    def __init__(self, args):
        self.args = args
        self.game_name = os.path.splitext(os.path.basename(args.rom))[0]
        self.tab = self.VIEWS.index(args.tab) if args.tab in self.VIEWS else 0
        self.ui = {}           # per-screen state
        self.dirty = threading.Event()
        self.dirty.set()
        self.text_cache = {}
        self.mem = None        # the game's memory poller: snapshot(), view
        self.ready = False     # game data loaded
        self.actions = queue.Queue()  # right-stick steps from the stick thread

    def load_game(self):
        """Reads what's needed from the ROM, starts self.mem, sets self.ready. Runs in a thread."""
        raise NotImplementedError

    @property
    def view(self):
        return self.VIEWS[self.tab]

    def set_tab(self, tab):
        self.tab = tab
        if self.mem:
            self.mem.view = self.view
        self.on_tab_change()

    def on_tab_change(self):
        pass

    # ---------- SDL setup ----------

    def open_window(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "wayland")
        os.environ["SDL_VIDEO_WAYLAND_WMCLASS"] = APP_ID
        os.environ["SDL_APP_ID"] = APP_ID
        sdl.SetHint(b"SDL_VIDEO_WAYLAND_WMCLASS", APP_ID.encode())
        sdl.SetHint(b"SDL_RENDER_SCALE_QUALITY", b"nearest")
        if sdl.Init(sdl.INIT_VIDEO) != 0 or sdl.TTF_Init() != 0:
            raise RuntimeError("SDL init: %s" % sdl.error())
        self.win = sdl.CreateWindow(b"mgba-qol", sdl.WINDOWPOS_UNDEFINED, sdl.WINDOWPOS_UNDEFINED,
                                    SCREEN_W, SCREEN_H, sdl.WINDOW_SHOWN | sdl.WINDOW_RESIZABLE)
        self.ren = sdl.CreateRenderer(self.win, -1, sdl.RENDERER_ACCELERATED | sdl.RENDERER_PRESENTVSYNC)
        if not self.win or not self.ren:
            raise RuntimeError("SDL window: %s" % sdl.error())
        # Lay out on 320x240 and let SDL double it with hard pixel edges.
        sdl.RenderSetLogicalSize(self.ren, W, H)
        sdl.RenderSetIntegerScale(self.ren, 1)
        sdl.SetRenderDrawBlendMode(self.ren, sdl.BLENDMODE_BLEND)
        self.font = sdl.TTF_OpenFont(FONT.encode(), FONT_SIZE)
        if not self.font:
            raise RuntimeError("font %s: %s" % (FONT, sdl.error()))

    def prepare_outputs(self):
        """Gets sway ready before our window exists, so it never lands next to the game.

        Mapping our window on the game's screen, even for a moment, can leave
        RetroArch rendering into a shrunken viewport until it is refocused.
        """
        out = self.args.output
        # Runtime rules last as long as this sway instance; add them once per instance.
        sway_pid = (subprocess.run(["pidof", "sway"], capture_output=True, text=True).stdout.split() or ["0"])[0]
        marker = "/tmp/mgbaqol-sway-rules-%s" % sway_pid
        if not os.path.exists(marker):
            swaymsg('for_window [app_id="%s"] move container to output %s, fullscreen enable' % (APP_ID, out))
            swaymsg('no_focus [app_id="%s"]' % APP_ID)
            open(marker, "w").close()
        # Let RetroArch map its window first; it must not see outputs change mid-start.
        for _ in range(100):
            if '"app_id": "%s"' % RA_APP_ID in swaymsg("-t", "get_tree"):
                break
            time.sleep(0.1)
        time.sleep(0.5)
        swaymsg("output", out, "power", "on")

    def place_window(self):
        """Makes sure our window ended up on the bottom screen and the game kept focus."""
        out = self.args.output
        for _ in range(50):
            if '"app_id": "%s"' % APP_ID in swaymsg("-t", "get_tree"):
                break
            time.sleep(0.1)
        swaymsg('[app_id="%s"] move container to output %s, fullscreen enable' % (APP_ID, out))
        for delay in (0.3, 1.5):
            time.sleep(delay)
            swaymsg('[app_id="%s"] focus' % RA_APP_ID)

    # ---------- drawing primitives (canvas units: 320x240) ----------

    def color(self, c, a=255):
        sdl.SetRenderDrawColor(self.ren, c[0], c[1], c[2], a)

    def rect(self, x, y, w, h, c, a=255):
        if w > 0 and h > 0:
            self.color(c, a)
            if a < 255:  # SDL2_gfx switches blending off after drawing anything opaque
                sdl.SetRenderDrawBlendMode(self.ren, sdl.BLENDMODE_BLEND)
            sdl.RenderFillRect(self.ren, ctypes.byref(sdl.Rect(int(x), int(y), int(w), int(h))))

    def box(self, x, y, w, h, c, a=255, radius=2):
        """Filled rectangle with clipped corners."""
        if w <= 0 or h <= 0:
            return
        if sdl.roundedBoxRGBA:
            sdl.roundedBoxRGBA(self.ren, x, y, x + w - 1, y + h - 1, radius, c[0], c[1], c[2], a)
        else:
            self.rect(x, y, w, h, c, a)

    def frame(self, x, y, w, h, fill=WIN, line=LINE, ink=INK):
        """A Gen 3 text window: dark outer border, light inner line."""
        self.box(x, y, w, h, ink, radius=3)
        self.box(x + 2, y + 2, w - 4, h - 4, fill, radius=2)
        if line and sdl.roundedRectangleRGBA:
            sdl.roundedRectangleRGBA(self.ren, x + 3, y + 3, x + w - 4, y + h - 4, 1, line[0], line[1], line[2], 255)

    def outline(self, x, y, w, h, c, thick=1):
        for k in range(thick):
            for rx, ry, rw, rh in ((x + k, y + k, w - 2 * k, 1), (x + k, y + h - 1 - k, w - 2 * k, 1),
                                   (x + k, y + k, 1, h - 2 * k), (x + w - 1 - k, y + k, 1, h - 2 * k)):
                self.rect(rx, ry, rw, rh, c)

    def text_tex(self, s, c):
        key = (s, c)
        hit = self.text_cache.get(key)
        if hit:
            return hit
        if len(self.text_cache) > 600:
            for tex, _, _ in self.text_cache.values():
                sdl.DestroyTexture(tex)
            self.text_cache.clear()
        surf = sdl.TTF_RenderUTF8_Solid(self.font, s.encode("utf-8"), sdl.Color(*c, 255))
        if not surf:
            return None
        w, h = surf.contents.w, surf.contents.h
        tex = sdl.CreateTextureFromSurface(self.ren, surf)
        sdl.FreeSurface(surf)
        self.text_cache[key] = (tex, w, h)
        return self.text_cache[key]

    def text(self, s, x, y, c=INK, shadow=SHADOW, align="left", alpha=255):
        """Pixel text with the Gen 3 one-pixel drop shadow. Returns its width."""
        if not s:
            return 0
        hit = self.text_tex(s, c)
        if not hit:
            return 0
        tex, w, h = hit
        if align == "right":
            x -= w
        elif align == "center":
            x -= w // 2
        if shadow:
            st = self.text_tex(s, shadow)
            if st:
                sdl.SetTextureAlphaMod(st[0], alpha)
                sdl.RenderCopy(self.ren, st[0], None, ctypes.byref(sdl.Rect(int(x) + 1, int(y) + 1, w, h)))
        sdl.SetTextureAlphaMod(tex, alpha)
        sdl.RenderCopy(self.ren, tex, None, ctypes.byref(sdl.Rect(int(x), int(y), w, h)))
        return w

    def arrow(self, x, y, d, c):
        """A 4x7 pixel triangle pointing r/l/u/d (the font has no arrow glyphs)."""
        for i in range(4):
            n = 7 - 2 * i
            if d == "r":
                self.rect(x + i, y + i, 1, n, c)
            elif d == "l":
                self.rect(x + 3 - i, y + i, 1, n, c)
            elif d == "d":
                self.rect(x + i, y + i, n, 1, c)
            else:
                self.rect(x + i, y + 3 - i, n, 1, c)

    def text_width(self, s):
        w, h = ctypes.c_int(), ctypes.c_int()
        sdl.TTF_SizeUTF8(self.font, s.encode("utf-8"), ctypes.byref(w), ctypes.byref(h))
        return w.value

    def fit(self, s, width):
        """s, cut with an ellipsis to fit width."""
        if self.text_width(s) <= width:
            return s
        while s and self.text_width(s + "...") > width:
            s = s[:-1]
        return s + "..."

    def wrap(self, s, width, max_lines):
        """Greedy word wrap measured with the real font; ellipsis if it overflows."""
        lines, cur = [], ""
        for word in s.split():
            trial = (cur + " " + word).strip()
            if self.text_width(trial) <= width or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = self.fit(lines[-1] + " ...", width)
        return lines

    def pill(self, label, x, y, bg, alpha=255):
        """A type / status plate: white text with an ink shadow. Returns its width."""
        label = label.upper()
        w = self.text_width(label) + 6
        self.box(x, y, w, 13, bg, alpha, radius=2)
        self.text(label, x + 3, y - 2, WHITE, INK, alpha=alpha)
        return w

    def hp_bar(self, x, y, w, hp, max_hp, alpha=255):
        """'HP' tag plus the bar, Gen 3 style; w covers both."""
        self.box(x, y, 17, 9, INK, alpha, radius=1)
        self.text("HP", x + 2, y - 4, YELLOW, None, alpha=alpha)
        bx, bw = x + 18, w - 18
        self.rect(bx, y, bw, 9, INK, alpha)
        self.rect(bx + 1, y + 1, bw - 2, 7, HP_BG, alpha)
        frac = hp / max_hp if max_hp else 0
        if hp > 0:
            c = GREEN if frac > 0.5 else YELLOW if frac > 0.2 else RED
            self.rect(bx + 1, y + 2, max(1, int((bw - 2) * frac)), 5, c, alpha)


    def chip(self, label, x, y, w, h, on):
        """A small selectable window (tabs, pocket and mode switches)."""
        self.box(x, y, w, h, INK, radius=2)
        self.box(x + 1, y + 1, w - 2, h - 2, WIN if on else WIN_DIM, radius=2)
        self.text(self.fit(label, w - 4), x + w // 2, y + (h - 16) // 2, INK if on else MUTED,
                  SHADOW if on else None, "center")

    def message(self, s, y0=TAB_H, h=H - TAB_H):
        """A one-line text window in the middle of the body."""
        w = min(W - 2 * PAD, self.text_width(s) + 24)
        x, y = (W - w) // 2, y0 + (h - 26) // 2
        self.frame(x, y, w, 26)
        self.text(s, W // 2, y + 5, align="center")

    # ---------- small widgets shared by the games ----------

    def bar(self, x, y, w, frac, c, h=5):
        self.rect(x, y, w, h, INK)
        self.rect(x + 1, y + 1, w - 2, h - 2, HP_BG)
        if frac > 0:
            self.rect(x + 1, y + 1, max(1, int((w - 2) * min(1, frac))), h - 2, c)

    def hp_color(self, hp, max_hp):
        f = hp / max_hp if max_hp else 0
        return GREEN if f > 0.5 else YELLOW if f > 0.25 else RED

    def tag(self, label, x, y, bg, fg):
        """A small chip with text; returns its width."""
        w = self.text_width(label) + 6
        self.box(x, y + 1, w, 14, bg, radius=2)
        self.text(label, x + 3, y - 1, fg, None)
        return w

    def tag_right(self, label, right, y, bg, fg):
        w = self.text_width(label) + 6
        self.tag(label, right - w, y, bg, fg)
        return w

    # ---------- screens ----------

    def draw(self):
        self.color(BG)
        sdl.RenderClear(self.ren)
        snap = self.mem.snapshot() if self.mem else {"connected": False}
        connected = snap.get("connected", False)
        self.draw_tabs(connected)
        if not self.ready:
            self.message("Loading game data...")
        elif self.view == "settings":
            self.draw_settings(snap)
        elif not connected:
            self.message("Waiting for the game...")
        else:
            self.draw_view(self.view, snap)
        sdl.RenderPresent(self.ren)

    def draw_view(self, view, snap):
        pass

    def draw_settings(self, snap):
        self.message(self.game_name)

    def draw_tabs(self, connected):
        self.rect(0, 0, W, TAB_H, BAR)
        self.rect(0, TAB_H - 2, W, 2, INK)
        tw = (W - GEAR_W) // len(self.TABS)
        for i, name in enumerate(self.TABS + [None]):
            x, w = (i * tw, tw) if i < len(self.TABS) else (W - GEAR_W, GEAR_W)
            on = i == self.tab
            if on:
                self.rect(x, 0, w, TAB_H, INK)
                self.rect(x + 1, 0, w - 2, TAB_H, WIN)
            c, sh = (INK, SHADOW) if on else (TAB_TEXT, TAB_SHADOW)
            if name:
                self.text(name.upper(), x + w // 2, 2, c, sh, "center")
            else:  # settings: three bars; a red dot over them when RetroArch isn't answering
                for k in range(3):
                    self.rect(x + w // 2 - 6, 6 + k * 4, 12, 2, c)
                if self.ready and not connected:
                    self.rect(x + w - 6, 3, 3, 3, RED)

    def animating(self):
        """True while the current view needs regular redraws (blinking)."""
        return False

    # ---------- input ----------

    def push_action(self, action):
        """From the stick thread: queue the step and wake the SDL loop."""
        self.actions.put(action)
        ev = (ctypes.c_uint8 * 56)()
        struct.pack_into("<I", ev, 0, sdl.EV_USER)
        sdl.PushEvent(ev)

    def on_stick(self, action):
        """Right stick: left/right switch tabs everywhere; the rest goes to the view."""
        if action in ("left", "right"):
            n = len(self.TABS)
            if self.view == "settings":
                self.set_tab(n - 1 if action == "left" else 0)
            else:
                self.set_tab((self.tab + (1 if action == "right" else -1)) % n)
            return
        snap = self.mem.snapshot() if self.mem else {}
        self.stick_view(self.view, action, snap)

    def stick_view(self, view, action, snap):
        """up / down / press on the current view."""

    def on_tap(self, x, y):
        if y < TAB_H:
            tw = (W - GEAR_W) // len(self.TABS)
            self.set_tab(len(self.TABS) if x >= W - GEAR_W else min(x // tw, len(self.TABS) - 1))
        else:
            self.tap_view(self.view, x, y)
        self.dirty.set()

    def tap_view(self, view, x, y):
        """A tap below the tab bar."""

    def run(self):
        self.prepare_outputs()
        self.open_window()
        threading.Thread(target=self.place_window, daemon=True).start()
        RightStick(self.push_action).start()
        self.draw()
        threading.Thread(target=self.load_game, daemon=True).start()
        ev = (ctypes.c_uint8 * 56)()
        last_alive = last_check = time.monotonic()
        while True:
            if sdl.WaitEventTimeout(ev, 200):
                while True:
                    raw = bytes(ev)
                    t = struct.unpack_from("<I", raw, 0)[0]
                    if t == sdl.EV_QUIT:
                        return
                    if t == sdl.EV_FINGERUP:
                        fx, fy = struct.unpack_from("<ff", raw, 24)
                        self.on_tap(int(fx * W), int(fy * H))
                    elif t == sdl.EV_MOUSEUP and struct.unpack_from("<I", raw, 12)[0] != sdl.TOUCH_MOUSEID:
                        # Mouse coordinates already come in canvas units (logical size).
                        self.on_tap(*struct.unpack_from("<ii", raw, 20))
                    elif t == sdl.EV_WINDOW:
                        self.dirty.set()
                    if not sdl.PollEvent(ev):
                        break
            while not self.actions.empty():
                self.on_stick(self.actions.get_nowait())
                self.dirty.set()
            if self.animating():
                phase = int(time.monotonic() * 2)
                if phase != getattr(self, "_phase", None):
                    self._phase = phase
                    self.dirty.set()
            if self.dirty.is_set():
                self.dirty.clear()
                self.draw()
            now = time.monotonic()
            if now - last_check < 1:
                continue
            last_check = now
            if retroarch_running(self.args.ra_pid):
                last_alive = now
            elif now - last_alive > 3:
                log("RetroArch is gone, exiting")
                return

