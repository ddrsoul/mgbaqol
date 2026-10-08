# SPDX-License-Identifier: GPL-2.0-or-later
"""Gen 3 Pokemon companion: party, battle, bag and map, read live from the game."""

import ctypes

import games
import gen3
import sdl
from base import BaseApp, log
from memory import GameMemory
from ra import RetroArch
from romdata import RomData
from screens import Screens
from theme import *  # noqa: F401,F403 - geometry, font, colours


class PokemonApp(Screens, BaseApp):
    TABS = TABS
    VIEWS = VIEWS

    def __init__(self, args):
        super().__init__(args)
        self.rom = None
        self.detail = args.detail
        if args.map_mode:
            self.ui["map_mode"] = args.map_mode
        self.sprite_cache = {}

    def load_game(self):
        """Scans the ROM (slow on first run, cached afterwards) and starts polling."""
        self.rom = RomData(self.args.rom)
        self.ready = True
        prof = games.match(self.rom.rom)
        title, code = games.header(self.rom.rom)
        log("ROM %s (%s, crc %s), profile %s" % (title, code, self.rom.crc, prof and prof[0]))
        log("tables: %s" % self.rom.t)
        self.mem = GameMemory(RetroArch(port=self.args.port), self.rom, prof, self.dirty.set)
        self.mem.view = self.view
        self.mem.start()
        self.dirty.set()

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

    def on_tab_change(self):
        self.detail = None

    def draw_view(self, view, snap):
        party = snap.get("party") or []
        if view == "battle":
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

    def card_rects(self):
        cw, ch = (W - 3 * PAD) // 2, (H - TAB_H - 4 * PAD) // 3
        return [(PAD + (i % 2) * (cw + PAD), TAB_H + PAD + (i // 2) * (ch + PAD), cw, ch) for i in range(6)]

    def draw_party(self, party):
        sel = self.ui.get("party_sel") if self.ui.get("stick") else None
        for i, (x, y, w, h) in enumerate(self.card_rects()):
            if i < len(party):
                self.draw_card(party[i], x, y, w, h)
                if i == sel:  # the stick's cursor
                    self.outline(x + 2, y + 2, w - 4, h - 4, INK, 2)
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

    def stick_view(self, view, action, snap):
        """Right stick up/down/press: move through the current list."""
        step = 1 if action == "down" else -1 if action == "up" else 0
        if view == "party":
            party = snap.get("party") or []
            if not party:
                return
            if self.detail is not None:
                if action == "press":
                    self.detail = None
                else:
                    moves = party[self.detail]["moves"]
                    filled = [i for i, mv in enumerate(moves) if mv] or [0]
                    cur = self.ui.get("move", 0)
                    pos = filled.index(cur) if cur in filled else 0
                    self.ui["move"] = filled[(pos + step) % len(filled)]
            else:
                sel = min(self.ui.get("party_sel", 0), len(party) - 1)
                if action == "press":
                    if self.ui.get("stick"):
                        self.detail, self.ui["move"] = sel, 0
                else:
                    sel = (sel + step) % len(party) if self.ui.get("stick") else sel
                self.ui["party_sel"] = sel
                self.ui["stick"] = True
        elif view == "bag":
            self.bag_step(step, snap)
        elif view == "map":
            if action == "press":
                self.ui["map_mode"] = "Wild" if self.ui.get("map_mode", "Map") == "Map" else "Map"
            else:
                self.wild_step(step, snap)

    def tap_view(self, view, x, y):
        if view == "party":
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
            self.on_screen_tap(view, x, y)
