# SPDX-License-Identifier: GPL-2.0-or-later
"""Battle, Bag, Map and Settings views. Mixed into App, which owns the drawing helpers."""

import ctypes
import threading
import time

import gen3
import sdl
import typechart
from theme import (ACCENT, BAR_BG, FOOT_H, GREEN, H, LINE, MUTED, PAD, PANEL, RED, STATUS_COLORS, TAB_H,
                   TEXT, TYPE_COLORS, W, YELLOW)

STAGE_NAMES = ["HP", "Atk", "Def", "Spe", "SpA", "SpD", "Acc", "Eva"]
BAG_COLS, BAG_ROWS, BAG_ROW_H = 2, 9, 29


def effect_label(mult):
    if mult == 0:
        return "No effect", MUTED
    if mult < 1:
        return "×%s  Not very effective" % ("0.25" if mult < 0.5 else "0.5"), YELLOW
    if mult > 1:
        return "×%d  Super effective" % mult, GREEN
    return "×1  Normal damage", TEXT


class Screens:
    # ---------- battle ----------

    def draw_battle(self, snap, y0, h):
        if not snap.get("in_battle"):
            self.message("Not in a battle", y0, h - 30)
            self.text("The opponent and your move matchups show up here during battles.",
                      W // 2, y0 + h // 2 + 6, "small", MUTED, "center")
            return
        mons = snap.get("battle")
        if not mons or not mons[0] or len(mons) < 2 or not mons[1]:
            self.message("Looking for battle data…", y0, h)
            return
        me, foe = mons[0], mons[1]
        foe_types = [self.rom.type_name(t) for t in dict.fromkeys(foe["types"])]
        my_types = [self.rom.type_name(t) for t in dict.fromkeys(me["types"])]

        # Opponent card.
        x, y, w = PAD, y0 + PAD, W - PAD * 2
        self.rect(x, y, w, 112, PANEL, radius=10)
        tint = TYPE_COLORS.get(foe_types[0], MUTED) if foe_types else MUTED
        self.rect(x + 10, y + 10, 92, 92, tuple(v // 4 for v in tint), radius=8)
        self.sprite(foe["species"], x + 24, y + 24)
        tx, tr = x + 116, x + w - 12
        name = self.rom.species_name(foe["species"])
        nick = foe["nick"] if foe["nick"] and foe["nick"].upper() != name.upper() else ""
        self.text(nick or name, tx, y + 8, "big")
        self.text("Lv %d" % foe["level"], tr, y + 14, "body", MUTED, "right")
        px = tx
        for t in foe_types:
            px += self.pill(t, px, y + 42, TYPE_COLORS.get(t, MUTED)) + 4
        st = gen3.status_name(foe["status"])
        if st:
            px += self.pill(st, px, y + 42, STATUS_COLORS.get(st, MUTED)) + 4
        if nick:
            self.text(name, px + 6, y + 42, "small", MUTED)
        self.hp_bar(tx, y + 68, tr - tx, foe["hp"], foe["max_hp"], h=10)
        pct = 100 * foe["hp"] // foe["max_hp"] if foe["max_hp"] else 0
        self.text("HP %d / %d  (%d%%)" % (foe["hp"], foe["max_hp"], pct), tx, y + 84, "small", MUTED)
        self.stage_chips(foe["stages"], tr, y + 84)

        # Your active Pokemon.
        y += 120
        self.rect(x, y, w, 40, BAR_BG, radius=8)
        my_name = self.rom.species_name(me["species"])
        nw = self.text("Your", x + 12, y + 12, "small", MUTED)
        nw += self.text(me["nick"] or my_name, x + 18 + nw, y + 10, "title")
        self.text("Lv %d" % me["level"], x + 28 + nw, y + 12, "small", MUTED)
        self.hp_bar(x + 230, y + 16, 140, me["hp"], me["max_hp"])
        self.text("%d / %d" % (me["hp"], me["max_hp"]), x + 380, y + 11, "small", MUTED)
        self.stage_chips(me["stages"], x + w - 12, y + 11)

        # Your moves against the opponent.
        y += 46
        self.text("Your moves vs %s" % (nick or name), x + 4, y, "small", MUTED)
        y += 20
        mw, mh = (w - 8) // 2, (y0 + h - PAD - y - 8) // 2
        scored = []
        for i, move in enumerate(me["moves"]):
            info = self.rom.move_info(move) if move else None
            if info and info["power"]:
                stab = 1.5 if info["type"] in my_types else 1
                scored.append((info["power"] * stab * typechart.multiplier(info["type"], foe_types), i))
        best = max(scored)[1] if scored and max(scored)[0] > 0 else None
        for i, move in enumerate(me["moves"]):
            mx, my = x + (i % 2) * (mw + 8), y + (i // 2) * (mh + 8)
            if not move:
                self.outline(mx, my, mw, mh, LINE)
                continue
            info = self.rom.move_info(move)
            self.rect(mx, my, mw, mh, PANEL, radius=8)
            name_w = self.text(self.rom.move_name(move), mx + 10, my + 8, "title")
            if i == best:
                # Highest power x type effectiveness x STAB against this opponent.
                self.outline(mx, my, mw, mh, GREEN)
                self.pill("Best", mx + 18 + name_w, my + 9, GREEN)
            if not info:
                continue
            mtype = info["type"]
            self.pill(mtype, mx + mw - 10 - (self.text_tex(mtype, "tiny", (16, 19, 26))[1] + 12),
                      my + 9, TYPE_COLORS.get(mtype, MUTED))
            if info["power"]:
                label, color = effect_label(typechart.multiplier(mtype, foe_types))
                if mtype in my_types and color is not MUTED:
                    label += "  ·  STAB"
            else:
                label, color = "Status move", MUTED
            self.text(label, mx + 10, my + 34, "body", color)
            parts = ["PP %d/%d" % (me["pp"][i], info["pp"])]
            if info["power"] > 1:
                parts.append("Power %d" % info["power"])
            if info["acc"]:
                parts.append("Acc %d" % info["acc"])
            if info["priority"]:
                parts.append("Priority %+d" % info["priority"])
            self.text("  ·  ".join(parts), mx + 10, my + 58, "small", MUTED)

    def stage_chips(self, stages, right, y):
        """Non-zero stat stages, right-aligned, e.g. 'Atk +1  Spe -2'."""
        chips = ["%s %+d" % (STAGE_NAMES[k], v) for k, v in enumerate(stages) if v and k]
        x = right
        for chip in reversed(chips):
            color = GREEN if "+" in chip else RED
            x -= self.text(chip, x, y, "small", color, "right") + 10

    # ---------- bag ----------

    def draw_bag(self, snap, y0, h):
        bag = snap.get("bag")
        if bag is None:
            self.message("Looking for the bag…", y0, h)
            return
        sel = min(self.ui.get("pocket", 0), len(bag) - 1)
        x, w = PAD, W - PAD * 2
        cw = w // len(bag)
        for i, (name, items) in enumerate(bag):
            cx = x + i * cw
            on = i == sel
            self.rect(cx + 2, y0 + 8, cw - 4, 30, PANEL if on else BAR_BG, radius=8)
            if on:
                self.outline(cx + 2, y0 + 8, cw - 4, 30, ACCENT)
            font = "small" if self.text_width(name, "small") <= cw - 12 else "tiny"
            self.text(name, cx + cw // 2, y0 + (15 if font == "small" else 17), font, TEXT if on else MUTED, "center")
        items = bag[sel][1]
        per_page = BAG_COLS * BAG_ROWS
        pages = max(1, (len(items) + per_page - 1) // per_page)
        page = min(self.ui.get("page", 0), pages - 1)
        list_y = y0 + 46
        colw = (w - 8) // BAG_COLS
        chosen = self.ui.get("item")
        if not items:
            self.message("This pocket is empty", list_y, BAG_ROWS * BAG_ROW_H)
        for k, (item, qty) in enumerate(items[page * per_page:(page + 1) * per_page]):
            col, row = k // BAG_ROWS, k % BAG_ROWS
            ix, iy = x + col * (colw + 8), list_y + row * BAG_ROW_H
            if item == chosen:
                self.rect(ix, iy, colw, BAG_ROW_H - 3, PANEL, radius=6)
            self.text(self.rom.item_name(item), ix + 8, iy + 5, "body", TEXT)
            if bag[sel][0] != "Key Items" or qty > 1:
                self.text("×%d" % qty, ix + colw - 8, iy + 5, "body", MUTED, "right")
        py = list_y + BAG_ROWS * BAG_ROW_H + 2
        if pages > 1:
            self.text("‹", x + 20, py - 2, "big", TEXT if page else LINE, "center")
            self.text("Page %d of %d" % (page + 1, pages), W // 2, py + 4, "small", MUTED, "center")
            self.text("›", x + w - 20, py - 2, "big", TEXT if page < pages - 1 else LINE, "center")
        dy = py + 30
        self.rect(x, dy, w, y0 + h - PAD - dy, PANEL, radius=8)
        if chosen and any(item == chosen for item, _ in items):
            self.text(self.rom.item_name(chosen), x + 12, dy + 6, "title")
            for n, line in enumerate(self.wrap(self.rom.item_description(chosen), "small", w - 24, 2)):
                self.text(line, x + 12, dy + 28 + n * 17, "small", TEXT)
        else:
            self.text("Tap an item to see what it does", x + 12, dy + 20, "small", MUTED)

    def bag_tap(self, x, y, snap):
        bag = snap.get("bag")
        if not bag:
            return
        y0 = TAB_H
        if y0 + 8 <= y < y0 + 38:
            self.ui.update(pocket=min((x - PAD) * len(bag) // (W - PAD * 2), len(bag) - 1), page=0, item=None)
            return
        sel = min(self.ui.get("pocket", 0), len(bag) - 1)
        items = bag[sel][1]
        per_page = BAG_COLS * BAG_ROWS
        pages = max(1, (len(items) + per_page - 1) // per_page)
        page = min(self.ui.get("page", 0), pages - 1)
        list_y = y0 + 46
        py = list_y + BAG_ROWS * BAG_ROW_H + 2
        if py - 4 <= y < py + 26:
            self.ui["page"] = max(0, page - 1) if x < W // 2 else min(pages - 1, page + 1)
            return
        if list_y <= y < py:
            colw = (W - PAD * 2 - 8) // BAG_COLS
            col, row = min((x - PAD) // (colw + 8), BAG_COLS - 1), (y - list_y) // BAG_ROW_H
            k = page * per_page + col * BAG_ROWS + row
            if k < len(items):
                self.ui["item"] = items[k][0]

    # ---------- map ----------

    MAP_MODES = ("Map", "Wild")

    def draw_map(self, snap, y0, h):
        loc = snap.get("location")
        if not loc and self.args.debug_mapsec is not None:
            loc = {"mapsec": self.args.debug_mapsec, "group": None, "num": None}
        if not loc:
            self.message("Looking for your location…", y0, h)
            return
        x, w = PAD, W - PAD * 2
        name = self.rom.mapsec_name(loc["mapsec"]) if loc["mapsec"] is not None else None
        self.text(name or "Unknown area", x + 6, y0 + 8, "big")
        mode = self.ui.get("map_mode", "Map")
        for i, m in enumerate(self.MAP_MODES):
            cx = W - PAD - (len(self.MAP_MODES) - i) * 84
            on = m == mode
            self.rect(cx, y0 + 8, 80, 30, PANEL if on else BAR_BG, radius=8)
            if on:
                self.outline(cx, y0 + 8, 80, 30, ACCENT)
            self.text(m, cx + 40, y0 + 14, "body", TEXT if on else MUTED, "center")
        if mode == "Map":
            self.draw_region(loc, y0 + 46, h - 46)
        else:
            self.draw_wild(loc, y0 + 46, h - 46)

    def draw_region(self, loc, y0, h):
        if not hasattr(self.rom, "_region_map"):
            if not getattr(self, "_map_thread", None):
                self._map_thread = threading.Thread(target=self._build_region_map, daemon=True)
                self._map_thread.start()
            self.message("Drawing the map…", y0, h)
            return
        m = self.rom.region_map()
        if not m:
            self.message("No region map for this game", y0, h)
            return
        sec = m["sections"].get(loc["mapsec"])
        image = sec[0] if sec else 0
        iw, ih, _ = m["images"][image]
        scale = 2
        mx, my = (W - iw * scale) // 2, y0 + (h - PAD - ih * scale) // 2
        tex = self.map_texture(image, m)
        if tex:
            sdl.RenderCopy(self.ren, tex, None, ctypes.byref(sdl.Rect(mx, my, iw * scale, ih * scale)))
        if sec:
            _, sx, sy, sw, sh = sec
            fx, fy, fw, fh = mx + sx * scale, my + sy * scale, sw * scale, sh * scale
            self.rect(fx, fy, fw, fh, RED, 120)
            if int(time.monotonic() * 2) % 2 == 0:  # blinking 3 px frame
                for k in range(1, 4):
                    self.outline(fx - k, fy - k, fw + 2 * k, fh + 2 * k, (255, 255, 255), radius=2)
        else:
            self.text("Not shown on the map", W // 2, my + ih * scale + 2, "small", MUTED, "center")

    def _build_region_map(self):
        self.rom.region_map()
        self.dirty.set()

    def map_texture(self, image, m):
        cache = self.__dict__.setdefault("_map_tex", {})
        if image not in cache:
            iw, ih, rgba = m["images"][image]
            tex = sdl.CreateTexture(self.ren, sdl.PIXELFORMAT_ABGR8888, sdl.TEXTUREACCESS_STATIC, iw, ih)
            buf = ctypes.create_string_buffer(rgba, len(rgba))
            sdl.UpdateTexture(tex, None, buf, iw * 4)
            cache[image] = tex
        return cache[image]

    def animating(self):
        """The Map view blinks the current location, so it needs regular redraws."""
        return self.ui.get("map_mode", "Map") == "Map"

    def draw_wild(self, loc, y0, h):
        x, w = PAD, W - PAD * 2
        wild = self.rom.wild_encounters(loc["group"], loc["num"]) if loc["group"] is not None else {}
        if not wild:
            self.message("No wild Pokémon here", y0, h)
            return
        methods = list(wild)
        sel = self.ui.get("method") if self.ui.get("method") in methods else methods[0]
        cy = y0
        cw = min(150, w // len(methods))
        for i, m in enumerate(methods):
            on = m == sel
            self.rect(x + i * cw + 2, cy, cw - 4, 28, PANEL if on else BAR_BG, radius=8)
            if on:
                self.outline(x + i * cw + 2, cy, cw - 4, 28, ACCENT)
            self.text(m, x + i * cw + cw // 2, cy + 6, "small", TEXT if on else MUTED, "center")
        entries = wild[sel]
        gy = cy + 36
        cols = 6
        cellw = w // cols
        cellh = (y0 + h - PAD - gy) // 2
        for k, (species, lo, hi, pct, note) in enumerate(entries[:cols * 2]):
            ex, ey = x + (k % cols) * cellw, gy + (k // cols) * cellh
            self.rect(ex + 2, ey, cellw - 4, cellh - 6, PANEL, radius=8)
            self.sprite(species, ex + (cellw - 64) // 2, ey + 2)
            self.text(self.rom.species_name(species), ex + cellw // 2, ey + 66, "small", TEXT, "center")
            lv = "Lv %d" % lo if lo == hi else "Lv %d–%d" % (lo, hi)
            self.text("%s · %d%%" % (lv, pct), ex + cellw // 2, ey + 83, "small", MUTED, "center")
            if note:
                self.text(note, ex + cellw // 2, ey + 100, "small", MUTED, "center")
        if len(entries) > cols * 2:
            self.text("+%d more" % (len(entries) - cols * 2), x + w, y0 + h - 4, "small", MUTED, "right")

    def map_tap(self, x, y, snap):
        y0 = TAB_H
        if y0 + 8 <= y < y0 + 38:
            for i, m in enumerate(self.MAP_MODES):
                cx = W - PAD - (len(self.MAP_MODES) - i) * 84
                if cx <= x < cx + 80:
                    self.ui["map_mode"] = m
            return
        loc = snap.get("location")
        if self.ui.get("map_mode", "Map") != "Wild" or not loc or loc["group"] is None:
            return
        methods = list(self.rom.wild_encounters(loc["group"], loc["num"]))
        cy = y0 + 46
        if methods and cy <= y < cy + 28:
            cw = min(150, (W - PAD * 2) // len(methods))
            i = (x - PAD) // cw
            if 0 <= i < len(methods):
                self.ui["method"] = methods[i]

    # ---------- settings ----------

    def draw_settings(self, snap, y0, h):
        x, w = PAD, W - PAD * 2
        y = y0 + PAD
        self.text("Party data", x + 4, y, "title")
        self.text("Where the companion reads your team from. Auto learns it while you play.",
                  x + 4, y + 22, "small", MUTED)
        y += 46
        mode = snap.get("party_mode", "auto")
        rows = [("auto", "Auto", "In use: %s" % ("0x%08X" % snap["learned"] if snap.get("learned") else
                                                  "0x%08X" % snap["party_addr"] if snap.get("party_addr") else "—"))]
        for c in snap.get("candidates", []):
            names = (snap.get("previews") or {}).get(c)
            preview = ", ".join(self.rom.species_name(s) for s in names[:3]) + (
                " +%d" % (len(names) - 3) if len(names) > 3 else "") if names else "empty right now"
            rows.append(("%08X" % c, "0x%08X" % c, preview))
        self._settings_rows = []
        for key, label, sub in rows[:4]:
            on = mode == key
            self.rect(x, y, w, 34, PANEL if on else BAR_BG, radius=8)
            if on:
                self.outline(x, y, w, 34, ACCENT)
            self.text("●" if on else "○", x + 14, y + 7, "body", ACCENT if on else MUTED)
            self.text(label, x + 36, y + 7, "body", TEXT)
            self.text(sub, x + w - 12, y + 9, "small", MUTED, "right")
            self._settings_rows.append((y, key))
            y += 38
        self._settings_buttons = []
        bw = (w - 8) // 2
        for i, (label, action) in enumerate((("Scan RAM again", "rescan_party"),
                                             ("Forget found addresses", "reset"))):
            bx = x + i * (bw + 8)
            self.rect(bx, y, bw, 34, BAR_BG, radius=8)
            self.outline(bx, y, bw, 34, LINE)
            self.text(label, bx + bw // 2, y + 8, "body", TEXT, "center")
            self._settings_buttons.append((bx, y, bw, action))
        y += 46
        self.text("Found in RAM", x + 4, y, "title")
        y += 24
        found = snap.get("found", {})
        for key, label, hint in (("gmain", "Battle flag", "searched on start"),
                                 ("battle_mons", "Battle data", "found in your next battle"),
                                 ("bag_pockets", "Bag", "found when you open Bag"),
                                 ("map_header", "Location", "found when you open Map")):
            val = "0x%08X" % found[key] if key in found else hint
            self.text(label, x + 4, y, "small", MUTED)
            self.text(val, x + 150, y, "small", TEXT if key in found else MUTED)
            y += 18
        title, code = self.rom.rom[0xA0:0xAC].decode("ascii", "replace").rstrip("\0 "), \
            self.rom.rom[0xAC:0xB0].decode("ascii", "replace")
        self.text("%s  ·  %s  ·  CRC %s" % (title, code, self.rom.crc), x + 4, y0 + h - 22, "small", MUTED)

    def settings_tap(self, x, y, snap):
        if not self.mem:
            return
        for ry, key in getattr(self, "_settings_rows", []):
            if ry <= y < ry + 34:
                self.mem.set_party_mode(key)
                return
        for bx, by, bw, action in getattr(self, "_settings_buttons", []):
            if bx <= x < bx + bw and by <= y < by + 34:
                self.mem.request(action)
                return

    def on_screen_tap(self, view, x, y):
        snap = self.mem.snapshot() if self.mem else {}
        {"bag": self.bag_tap, "map": self.map_tap, "settings": self.settings_tap}.get(
            view, lambda *a: None)(x, y, snap)
