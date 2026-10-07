#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""mgba-qol bottom-screen companion: live Gen 3 party view for RetroArch + mGBA.

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

from theme import *  # noqa: F401,F403 - geometry, fonts, colours

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


class App(Screens):
    def __init__(self, args):
        self.args = args
        self.game_name = os.path.splitext(os.path.basename(args.rom))[0]
        self.rom = None
        self.supported = False
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
        self.supported = True  # unknown games are searched for in RAM
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
        self.win = sdl.CreateWindow(b"mgba-qol", sdl.WINDOWPOS_UNDEFINED, sdl.WINDOWPOS_UNDEFINED, W, H,
                                    sdl.WINDOW_SHOWN | sdl.WINDOW_RESIZABLE)
        self.ren = sdl.CreateRenderer(self.win, -1, sdl.RENDERER_ACCELERATED | sdl.RENDERER_PRESENTVSYNC)
        if not self.win or not self.ren:
            raise RuntimeError("SDL window: %s" % sdl.error())
        sdl.SetRenderDrawBlendMode(self.ren, sdl.BLENDMODE_BLEND)
        self.fonts = {}
        for key, path, size in (("title", FONT_BOLD, 17), ("body", FONT_REGULAR, 15),
                                ("small", FONT_REGULAR, 13), ("tiny", FONT_BOLD, 11),
                                ("big", FONT_BOLD, 24), ("tab", FONT_REGULAR, 15)):
            font = sdl.TTF_OpenFont(path.encode(), size)
            if not font:
                raise RuntimeError("font %s: %s" % (path, sdl.error()))
            self.fonts[key] = font

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

    # ---------- drawing helpers ----------

    def color(self, c, a=255):
        sdl.SetRenderDrawColor(self.ren, c[0], c[1], c[2], a)

    def rect(self, x, y, w, h, c, a=255, radius=0):
        if w <= 0 or h <= 0:
            return
        if radius and sdl.roundedBoxRGBA:
            sdl.roundedBoxRGBA(self.ren, x, y, x + w - 1, y + h - 1, radius, c[0], c[1], c[2], a)
        else:
            self.color(c, a)
            sdl.RenderFillRect(self.ren, ctypes.byref(sdl.Rect(int(x), int(y), int(w), int(h))))

    def outline(self, x, y, w, h, c, radius=8):
        if sdl.roundedRectangleRGBA:
            sdl.roundedRectangleRGBA(self.ren, x, y, x + w - 1, y + h - 1, radius, c[0], c[1], c[2], 255)

    def text_tex(self, text, font, c):
        key = (text, font, c)
        hit = self.text_cache.get(key)
        if hit:
            return hit
        if len(self.text_cache) > 400:
            for tex, _, _ in self.text_cache.values():
                sdl.DestroyTexture(tex)
            self.text_cache.clear()
        surf = sdl.TTF_RenderUTF8_Blended(self.fonts[font], text.encode("utf-8"), sdl.Color(*c, 255))
        if not surf:
            return None
        w, h = surf.contents.w, surf.contents.h
        tex = sdl.CreateTextureFromSurface(self.ren, surf)
        sdl.FreeSurface(surf)
        self.text_cache[key] = (tex, w, h)
        return self.text_cache[key]

    def text(self, s, x, y, font="body", c=TEXT, align="left", alpha=255):
        if not s:
            return 0
        hit = self.text_tex(s, font, c)
        if not hit:
            return 0
        tex, w, h = hit
        if align == "right":
            x -= w
        elif align == "center":
            x -= w // 2
        sdl.SetTextureAlphaMod(tex, alpha)
        sdl.RenderCopy(self.ren, tex, None, ctypes.byref(sdl.Rect(int(x), int(y), w, h)))
        return w

    def pill(self, label, x, y, bg, fg=(16, 19, 26), alpha=255):
        tex = self.text_tex(label, "tiny", fg)
        w = (tex[1] if tex else 20) + 12
        self.rect(x, y, w, 17, bg, alpha, radius=8)
        self.text(label, x + 6, y + 2, "tiny", fg, alpha=alpha)
        return w

    def hp_bar(self, x, y, w, hp, max_hp, h=8, alpha=255):
        self.rect(x, y, w, h, LINE, alpha, radius=h // 2)
        frac = hp / max_hp if max_hp else 0
        c = GREEN if frac > 0.5 else YELLOW if frac > 0.2 else RED
        if hp > 0:
            self.rect(x, y, max(h, int(w * frac)), h, c, alpha, radius=h // 2)

    def sprite(self, species, x, y, scale=1, alpha=255):
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
            sdl.RenderCopy(self.ren, tex, None, ctypes.byref(sdl.Rect(x, y, 64 * scale, 64 * scale)))
        else:
            name = self.rom.species_name(species)
            self.text(name[:1], x + 32 * scale, y + 20 * scale, "big", MUTED, "center", alpha)

    # ---------- screens ----------

    def draw(self):
        self.color(BG)
        sdl.RenderClear(self.ren)
        snap = self.mem.snapshot() if self.mem else {"connected": False, "party": []}
        connected, party = snap["connected"], snap.get("party") or []
        self.draw_tabs()
        body_y, body_h = TAB_H, H - TAB_H - FOOT_H
        view = VIEWS[self.tab]
        if self.rom is None:
            self.message("Loading game data…", body_y, body_h)
        elif view == "settings":
            self.draw_settings(snap, body_y, body_h)
        elif not connected:
            self.message("Waiting for the game…", body_y, body_h)
        elif view == "battle":
            self.draw_battle(snap, body_y, body_h)
        elif view == "bag":
            self.draw_bag(snap, body_y, body_h)
        elif view == "map":
            self.draw_map(snap, body_y, body_h)
        elif not party:
            self.message("No Pokémon in your party yet", body_y, body_h)
        elif self.detail is not None and self.detail < len(party):
            self.draw_detail(party[self.detail], body_y, body_h)
        else:
            self.detail = None
            self.draw_party(party, body_y, body_h)
        self.draw_footer(connected)
        sdl.RenderPresent(self.ren)

    def message(self, s, y, h):
        self.text(s, W // 2, y + h // 2 - 10, "body", MUTED, "center")

    def draw_tabs(self):
        self.rect(0, 0, W, TAB_H, BAR_BG)
        tw = (W - GEAR_W) // len(TABS)
        for i, name in enumerate(TABS + [None]):
            x, w = (i * tw, tw) if i < len(TABS) else (W - GEAR_W, GEAR_W)
            if i == self.tab:
                self.rect(x, 0, w, TAB_H, PANEL)
                self.rect(x, TAB_H - 3, w, 3, ACCENT)
            c = TEXT if i == self.tab else MUTED
            if name:
                self.text(name, x + w // 2, 10, "tab", c, "center")
            else:  # settings: a three-bar menu icon
                for k in range(3):
                    self.rect(x + w // 2 - 10, 12 + k * 7, 20, 3, c, radius=1)
        self.rect(0, TAB_H - 1, W, 1, LINE)

    def draw_footer(self, connected):
        y = H - FOOT_H
        self.rect(0, y, W, FOOT_H, BAR_BG)
        self.rect(0, y, W, 1, LINE)
        in_detail = self.tab == 0 and self.detail is not None
        self.text("Tap anywhere to go back" if in_detail else self.game_name, 12, y + 7, "small", MUTED)
        if connected:
            self.text("Live", W - 12, y + 7, "small", MUTED, "right")
            self.text("●", W - 46, y + 6, "small", GREEN, "right")
        else:
            self.text("Not connected", W - 12, y + 7, "small", MUTED, "right")

    def card_rects(self, y0, h):
        cw = (W - PAD * 3) // 2
        ch = (h - PAD * 4) // 3
        return [(PAD + (i % 2) * (cw + PAD), y0 + PAD + (i // 2) * (ch + PAD), cw, ch) for i in range(6)]

    def draw_party(self, party, y0, h):
        rects = self.card_rects(y0, h)
        for i, (x, y, w, ch) in enumerate(rects):
            if i >= len(party):
                self.outline(x, y, w, ch, LINE)
                continue
            self.draw_card(party[i], x, y, w, ch)

    def draw_card(self, m, x, y, w, h):
        fainted = m["hp"] == 0
        a = 130 if fainted else 255
        self.rect(x, y, w, h, PANEL, radius=8)
        types = self.rom.species_types(m["species"])
        tint = TYPE_COLORS.get(types[0], MUTED) if types else MUTED
        box = 76
        bx, by = x + 8, y + (h - box) // 2
        self.rect(bx, by, box, box, tuple(v // 4 for v in tint), a, radius=8)
        self.sprite(m["species"], bx + 6, by + 6, alpha=a)
        tx, tr = bx + box + 10, x + w - 10
        species = self.rom.species_name(m["species"])
        name = m["nick"] or species
        self.text(name, tx, y + 8, "title", TEXT, alpha=a)
        self.text("Lv %d" % m["level"], tr, y + 10, "small", MUTED, "right", a)
        px = tx
        for t in types:
            px += self.pill(t, px, y + 33, TYPE_COLORS.get(t, MUTED), alpha=a) + 4
        st = gen3.status_name(m["status"])
        if st:
            self.pill(st, px, y + 33, STATUS_COLORS.get(st, MUTED), alpha=a)
        if m["shiny"]:
            self.text("★", tr, y + 31, "body", YELLOW, "right", a)
        self.hp_bar(tx, y + 58, tr - tx, m["hp"], m["max_hp"], alpha=a)
        hp_text = "%d / %d" % (m["hp"], m["max_hp"]) + ("  fainted" if fainted else "")
        self.text(hp_text, tx, y + 70, "small", RED if fainted else MUTED)
        self.text(self.rom.item_name(m["item"]), tr, y + 70, "small", MUTED, "right", a)
        if name.upper() != species.upper():
            self.text(species, tx, y + 88, "small", MUTED, alpha=a)

    def draw_detail(self, m, y0, h):
        x, y, w = PAD, y0 + PAD, W - PAD * 2
        self.rect(x, y, w, h - PAD * 2, PANEL, radius=10)
        types = self.rom.species_types(m["species"])
        tint = TYPE_COLORS.get(types[0], MUTED) if types else MUTED
        self.rect(x + 12, y + 12, 140, 140, tuple(v // 4 for v in tint), radius=10)
        self.sprite(m["species"], x + 18, y + 18, scale=2)
        tx = x + 168
        species = self.rom.species_name(m["species"])
        name = m["nick"] or species
        self.text(name, tx, y + 12, "big")
        self.text("Lv %d" % m["level"], x + w - 14, y + 18, "body", MUTED, "right")
        sub = species if name.upper() != species.upper() else ""
        if m["shiny"]:
            sub = (sub + "  ★ shiny").strip()
        self.text(sub, tx, y + 44, "small", MUTED)
        px = tx
        for t in types:
            px += self.pill(t, px, y + 66, TYPE_COLORS.get(t, MUTED)) + 4
        st = gen3.status_name(m["status"])
        if st:
            self.pill(st, px, y + 66, STATUS_COLORS.get(st, MUTED))
        self.hp_bar(tx, y + 94, x + w - 14 - tx, m["hp"], m["max_hp"], h=10)
        self.text("HP %d / %d" % (m["hp"], m["max_hp"]), tx, y + 108, "small", MUTED)
        item = self.rom.item_name(m["item"])
        if item:
            self.text("Holds " + item, x + w - 14, y + 108, "small", MUTED, "right")
        sx = tx
        for k, v in m["stats"].items():
            self.text(k, sx, y + 132, "small", MUTED)
            self.text(str(v), sx + 34, y + 132, "small", TEXT)
            sx += 82
        my, mh = y + 160, 108
        mw = (w - 36) // 2
        for i, move in enumerate(m["moves"]):
            mx, mrow = x + 12 + (i % 2) * (mw + 12), my + (i // 2) * (mh + 8)
            if not move:
                self.outline(mx, mrow, mw, mh, LINE)
                continue
            self.rect(mx, mrow, mw, mh, BAR_BG, radius=8)
            self.text(self.rom.move_name(move), mx + 10, mrow + 7, "title")
            info = self.rom.move_info(move)
            if info:
                mtype = info["type"]
                self.pill(mtype, mx + mw - 10 - (self.text_tex(mtype, "tiny", (16, 19, 26))[1] + 12),
                          mrow + 8, TYPE_COLORS.get(mtype, MUTED))
                parts = ["PP %d/%d" % (m["pp"][i], info["pp"])]
                power = info["power"]
                parts.append("Power %d" % power if power > 1 else "Power varies" if power == 1 else "Status")
                if info["acc"]:
                    parts.append("Acc %d" % info["acc"])
                if 0 < info["chance"] < 100:
                    parts.append("Effect %d%%" % info["chance"])
                if info["priority"]:
                    parts.append("Priority %+d" % info["priority"])
                detail = "  ·  ".join(parts)
            else:
                detail = "PP %d" % m["pp"][i]
            self.text(detail, mx + 10, mrow + 31, "small", MUTED)
            for n, line in enumerate(self.wrap(self.rom.move_description(move), "small", mw - 20, 3)):
                self.text(line, mx + 10, mrow + 53 + n * 17, "small", TEXT)

    def wrap(self, s, font, width, max_lines):
        """Greedy word wrap measured with the real font; ellipsis if it overflows."""
        lines, cur = [], ""
        for word in s.split():
            trial = (cur + " " + word).strip()
            if self.text_width(trial, font) <= width or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            last = lines[-1]
            while last and self.text_width(last + "…", font) > width:
                last = last[:-1]
            lines[-1] = last.rstrip() + "…"
        return lines

    def text_width(self, s, font):
        w, h = ctypes.c_int(), ctypes.c_int()
        sdl.TTF_SizeUTF8(self.fonts[font], s.encode("utf-8"), ctypes.byref(w), ctypes.byref(h))
        return w.value

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
                self.detail = None
            else:
                for i, (cx, cy, cw, ch) in enumerate(self.card_rects(TAB_H, H - TAB_H - FOOT_H)):
                    if cx <= x < cx + cw and cy <= y < cy + ch:
                        self.detail = i
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
