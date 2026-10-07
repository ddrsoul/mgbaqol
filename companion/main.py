#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""mgba-qol bottom-screen companion: live Gen 3 Pokemon data for RetroArch + mGBA.

  python3 main.py --rom "/storage/roms/gba/Emerald Enhanced [v11021].gba"
"""

import argparse
import ctypes
import os
import signal
import struct
import subprocess
import sys
import threading
import time

import games
import gen3
import sdl
from memory import GameMemory
from ra import RetroArch
from romdata import RomData
from screens import Screens
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


class App(Screens):
    def __init__(self, args):
        self.args = args
        self.game_name = os.path.splitext(os.path.basename(args.rom))[0]
        self.rom = None
        self.tab = VIEWS.index(args.tab) if args.tab in VIEWS else 0
        self.detail = args.detail
        self.ui = {"map_mode": args.map_mode} if args.map_mode else {}  # per-screen state
        self.dirty = threading.Event()
        self.dirty.set()
        self.text_cache = {}
        self.sprite_cache = {}
        self.mem = None

    def load_game(self):
        """Scans the ROM (slow on first run, cached afterwards) and starts polling."""
        self.rom = RomData(self.args.rom)
        prof = games.match(self.rom.rom)
        title, code = games.header(self.rom.rom)
        log("ROM %s (%s, crc %s), profile %s" % (title, code, self.rom.crc, prof and prof[0]))
        log("tables: %s" % self.rom.t)
        self.mem = GameMemory(RetroArch(port=self.args.port), self.rom, prof, self.dirty.set)
        self.mem.view = VIEWS[self.tab]
        self.mem.start()
        self.dirty.set()

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

    def sprite(self, species, x, y, size=32, alpha=255):
        """Front sprite in a size x size canvas box; 32 = native resolution on screen."""
        if species not in self.sprite_cache:
            rgba = self.rom.sprite_rgba(species)
            tex = None
            if rgba:
                tex = sdl.CreateTexture(self.ren, sdl.PIXELFORMAT_ABGR8888, sdl.TEXTUREACCESS_STATIC, 64, 64)
                buf = ctypes.create_string_buffer(rgba, len(rgba))
                sdl.UpdateTexture(tex, None, buf, 64 * 4)
                sdl.SetTextureBlendMode(tex, sdl.BLENDMODE_BLEND)
            self.sprite_cache[species] = tex
        tex = self.sprite_cache[species]
        if tex:
            sdl.SetTextureAlphaMod(tex, alpha)
            sdl.RenderCopy(self.ren, tex, None, ctypes.byref(sdl.Rect(int(x), int(y), size, size)))
        else:
            self.text(self.rom.species_name(species)[:1], x + size // 2, y + size // 2 - 8, MUTED, None, "center")

    def sprite_box(self, species, types, x, y, size=32, alpha=255):
        tint = TYPE_COLORS.get(types[0], MUTED) if types else MUTED
        self.box(x, y, size + 4, size + 4, tuple((v + 2 * w) // 3 for v, w in zip(tint, WIN)), alpha, radius=2)
        self.sprite(species, x + 2, y + 2, size, alpha)

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

    # ---------- screens ----------

    def draw(self):
        self.color(BG)
        sdl.RenderClear(self.ren)
        snap = self.mem.snapshot() if self.mem else {"connected": False, "party": []}
        connected, party = snap["connected"], snap.get("party") or []
        self.draw_tabs(connected)
        view = VIEWS[self.tab]
        if self.rom is None:
            self.message("Loading game data...")
        elif view == "settings":
            self.draw_settings(snap)
        elif not connected:
            self.message("Waiting for the game...")
        elif view == "battle":
            self.draw_battle(snap)
        elif view == "bag":
            self.draw_bag(snap)
        elif view == "map":
            self.draw_map(snap)
        elif not party:
            self.message("No Pokémon in your party yet")
        elif self.detail is not None and self.detail < len(party):
            self.draw_detail(party[self.detail])
        else:
            self.detail = None
            self.draw_party(party)
        sdl.RenderPresent(self.ren)

    def draw_tabs(self, connected):
        self.rect(0, 0, W, TAB_H, BAR)
        self.rect(0, TAB_H - 2, W, 2, INK)
        tw = (W - GEAR_W) // len(TABS)
        for i, name in enumerate(TABS + [None]):
            x, w = (i * tw, tw) if i < len(TABS) else (W - GEAR_W, GEAR_W)
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
                if self.rom is not None and not connected:
                    self.rect(x + w - 6, 3, 3, 3, RED)

    def card_rects(self):
        cw, ch = (W - 3 * PAD) // 2, (H - TAB_H - 4 * PAD) // 3
        return [(PAD + (i % 2) * (cw + PAD), TAB_H + PAD + (i // 2) * (ch + PAD), cw, ch) for i in range(6)]

    def draw_party(self, party):
        for i, (x, y, w, h) in enumerate(self.card_rects()):
            if i < len(party):
                self.draw_card(party[i], x, y, w, h)
            else:
                self.frame(x, y, w, h, fill=WIN_DIM, line=None)

    def draw_card(self, m, x, y, w, h):
        fainted = m["hp"] == 0
        a = 140 if fainted else 255
        self.frame(x, y, w, h)
        types = self.rom.species_types(m["species"])
        self.sprite_box(m["species"], types, x + 5, y + (h - 36) // 2, alpha=a)
        tx, tr = x + 46, x + w - 7
        species = self.rom.species_name(m["species"])
        lv = "Lv%d" % m["level"]
        self.text(lv, tr, y + 3, alpha=a, align="right")
        self.text(self.fit(m["nick"] or species, tr - tx - self.text_width(lv) - 4), tx, y + 3, alpha=a)
        px = tx
        for t in types:
            px += self.pill(t, px, y + 23, TYPE_COLORS.get(t, MUTED), a) + 2
        st = gen3.status_name(m["status"])
        if st:
            self.pill(st, px, y + 23, STATUS_COLORS.get(st, MUTED), a)
        self.hp_bar(tx, y + 41, tr - tx, m["hp"], m["max_hp"], a)
        self.text("FNT" if fainted else "%d/%d" % (m["hp"], m["max_hp"]), tr, y + 48,
                  RED if fainted else INK, align="right")
        if m["shiny"]:
            self.text("Shiny", tx, y + 48, YELLOW, INK, alpha=a)

    def draw_detail(self, m):
        """Like the game's Summary screen: the Pokemon, its moves, the chosen move's text."""
        x, w = PAD, W - 2 * PAD
        y = TAB_H + PAD
        self.frame(x, y, w, 78)
        types = self.rom.species_types(m["species"])
        self.sprite_box(m["species"], types, x + 5, y + 5, size=64)
        tx, tr = x + 76, x + w - 7
        species = self.rom.species_name(m["species"])
        name = m["nick"] or species
        lv = "Lv%d" % m["level"]
        self.text(lv, tr, y + 3, align="right")
        sub = species if name.upper() != species.upper() else ""
        self.text(self.fit(name + ("  /" + sub if sub else ""), tr - tx - 40), tx, y + 3)
        px = tx
        for t in types:
            px += self.pill(t, px, y + 22, TYPE_COLORS.get(t, MUTED)) + 2
        st = gen3.status_name(m["status"])
        if st:
            px += self.pill(st, px, y + 22, STATUS_COLORS.get(st, MUTED)) + 2
        if m["shiny"]:
            self.pill("Shiny", px, y + 22, YELLOW)
        item = self.rom.item_name(m["item"])
        if item:
            self.text(self.fit(item, 90), tr, y + 20, MUTED, None, "right")
        self.hp_bar(tx, y + 41, tr - tx - 52, m["hp"], m["max_hp"])
        self.text("%d/%d" % (m["hp"], m["max_hp"]), tr, y + 37, align="right")
        sx = tx
        for k in ("Atk", "Def", "SpA", "SpD", "Spe"):
            sx += self.text(k, sx, y + 56, MUTED, None) + 2
            sx += self.text(str(m["stats"][k]), sx, y + 56) + 6

        # Moves list.
        y += 82
        rows = 4
        self.frame(x, y, w, rows * 16 + 8)
        sel = min(self.ui.get("move", 0), 3)
        for i, move in enumerate(m["moves"]):
            ry = y + 4 + i * 16
            if not move:
                self.text("-", x + 12, ry, MUTED, None)
                continue
            if i == sel:
                self.rect(x + 4, ry, w - 8, 16, WIN_DIM)
                self.arrow(x + 7, ry + 5, "r", INK)
            info = self.rom.move_info(move)
            self.text(self.fit(self.rom.move_name(move), 130), x + 16, ry)
            if info:
                self.pill(info["type"], x + 152, ry + 2, TYPE_COLORS.get(info["type"], MUTED))
                self.text("PP %d/%d" % (m["pp"][i], info["pp"]), tr, ry, align="right")
        self._move_rows = (y + 4, 16)

        # The chosen move.
        y += rows * 16 + 12
        hgt = H - PAD - y
        self.frame(x, y, w, hgt)
        move = m["moves"][sel] if sel < len(m["moves"]) else 0
        if move:
            info = self.rom.move_info(move)
            parts = []
            if info:
                p = info["power"]
                parts.append("Power %d" % p if p > 1 else "Power varies" if p == 1 else "Status")
                if info["acc"]:
                    parts.append("Acc %d" % info["acc"])
                if 0 < info["chance"] < 100:
                    parts.append("Effect %d%%" % info["chance"])
                if info["priority"]:
                    parts.append("Priority %+d" % info["priority"])
            self.text("  ".join(parts), x + 8, y + 3, MUTED, None)
            for n, line in enumerate(self.wrap(self.rom.move_description(move), w - 16, (hgt - 22) // 15)):
                self.text(line, x + 8, y + 18 + n * 15)

    # ---------- input ----------

    def on_tap(self, x, y):
        if y < TAB_H:
            tw = (W - GEAR_W) // len(TABS)
            self.tab = len(TABS) if x >= W - GEAR_W else min(x // tw, len(TABS) - 1)
            self.detail = None
            if self.mem:
                self.mem.view = VIEWS[self.tab]
        elif VIEWS[self.tab] == "party":
            if self.detail is not None:
                top, row = getattr(self, "_move_rows", (0, 0))
                if row and top <= y < top + 4 * row:
                    self.ui["move"] = (y - top) // row
                else:
                    self.detail = None
            else:
                for i, (cx, cy, cw, ch) in enumerate(self.card_rects()):
                    if cx <= x < cx + cw and cy <= y < cy + ch:
                        self.detail = i
                        self.ui["move"] = 0
        else:
            self.on_screen_tap(VIEWS[self.tab], x, y)
        self.dirty.set()

    def run(self):
        self.prepare_outputs()
        self.open_window()
        threading.Thread(target=self.place_window, daemon=True).start()
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
            if VIEWS[self.tab] == "map" and self.animating():
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rom", required=True)
    ap.add_argument("--ra-pid", type=int, default=0)
    ap.add_argument("--port", type=int, default=55355)
    ap.add_argument("--output", default="DSI-1", help="sway output of the bottom screen")
    ap.add_argument("--detail", type=int, help="open this party slot's detail view (0-5), for testing")
    ap.add_argument("--tab", choices=VIEWS, help="start on this tab, for testing")
    ap.add_argument("--debug-mapsec", type=int, help="pretend to be in this map section when the game says nothing")
    ap.add_argument("--map-mode", choices=("Map", "Wild"), help="start the Map tab in this mode, for testing")
    ap.add_argument("--debug-battle", action="store_true", help="fake a battle from the party, for testing")
    args = ap.parse_args()

    app = App(args)

    def cleanup(*_):
        swaymsg("output", args.output, "power", "off")
        os._exit(0)

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)
    try:
        app.run()
    finally:
        cleanup()


if __name__ == "__main__":
    sys.exit(main())
