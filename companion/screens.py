# SPDX-License-Identifier: GPL-2.0-or-later
"""Battle, Bag, Map and Settings views. Mixed into App, which owns the drawing primitives.

All coordinates are on the 320x240 canvas.
"""

import ctypes
import threading
import time

import gen3
import sdl
import typechart
from theme import (BEST, GREEN, H, INK, LINE, MUTED, PAD, RED, SHADOW, STATUS_COLORS, TAB_H, TAB_SHADOW,
                   TAB_TEXT, TYPE_COLORS, W, WIN, WIN_DIM, WHITE)

STAGE_NAMES = ["HP", "Atk", "Def", "Spe", "SpA", "SpD", "Acc", "Eva"]
NOT_VERY = (176, 120, 16)  # dark amber: readable on the light windows
BAG_ROWS = 8
WILD_COLS, WILD_ROWS = 3, 4
# Fishing is split by rod; short labels so up to six modes fit one row.
WILD_LABELS = {"Grass": "Grass", "Surfing": "Surf", "Rock Smash": "Rock",
               "Old Rod": "Old", "Good Rod": "Good", "Super Rod": "Super"}


def effect_label(mult):
    if mult == 0:
        return "No effect", MUTED
    if mult < 1:
        return "×%s Not very effective" % ("0.25" if mult < 0.5 else "0.5"), NOT_VERY
    if mult > 1:
        return "×%d Super effective" % mult, BEST
    return "×1 Normal damage", INK


class Screens:
    # ---------- battle ----------

    def _debug_battle(self, snap):
        """Your first two party members as you and the opponent, for layout tests."""
        party = snap.get("party") or []
        if len(party) < 2:
            return None
        base, stride = self.rom.t["base_stats"]

        def mon(m, stages):
            off = base + m["species"] * stride + 6
            return dict(m, types=list(self.rom.rom[off:off + 2]), stages=stages)
        return [mon(party[0], [0] * 8), mon(party[1], [0, 1, 0, -2, 0, 0, 0, 0])]

    def draw_battle(self, snap):
        if self.args.debug_battle and not snap.get("in_battle"):
            snap = dict(snap, in_battle=True, battle=self._debug_battle(snap))
        if not snap.get("in_battle"):
            self.message("Not in a battle")
            return
        mons = snap.get("battle")
        if not mons or not mons[0] or len(mons) < 2 or not mons[1]:
            self.message("Looking for battle data...")
            return
        me, foe = mons[0], mons[1]
        foe_types = [self.rom.type_name(t) for t in dict.fromkeys(foe["types"])]
        my_types = [self.rom.type_name(t) for t in dict.fromkeys(me["types"])]
        x, w = PAD, W - 2 * PAD

        # Opponent.
        y = TAB_H + PAD
        self.frame(x, y, w, 58)
        self.sprite_box(foe["species"], foe_types, x + 5, y + 11)
        tx, tr = x + 46, x + w - 7
        name = self.rom.species_name(foe["species"])
        nick = foe["nick"] if foe["nick"] and foe["nick"].upper() != name.upper() else ""
        lv = "Lv%d" % foe["level"]
        self.text(lv, tr, y + 3, align="right")
        self.text(self.fit(nick + " / " + name if nick else name, tr - tx - 40), tx, y + 3)
        px = tx
        for t in foe_types:
            px += self.pill(t, px, y + 22, TYPE_COLORS.get(t, MUTED)) + 2
        st = gen3.status_name(foe["status"])
        if st:
            px += self.pill(st, px, y + 22, STATUS_COLORS.get(st, MUTED)) + 2
        self.stage_chips(foe["stages"], tr, y + 19)
        self.hp_bar(tx, y + 42, tr - tx - 72, foe["hp"], foe["max_hp"])
        pct = 100 * foe["hp"] // foe["max_hp"] if foe["max_hp"] else 0
        self.text("%d/%d %d%%" % (foe["hp"], foe["max_hp"], pct), tr, y + 38, align="right")

        # You.
        y += 62
        self.frame(x, y, w, 24, line=None)
        nw = self.text("Your", x + 6, y + 3, MUTED, None) + 4
        nw += self.text(self.fit(me["nick"] or self.rom.species_name(me["species"]), 80), x + 6 + nw, y + 3)
        self.text("Lv%d" % me["level"], x + 12 + nw, y + 3)
        self.hp_bar(x + 150, y + 8, 90, me["hp"], me["max_hp"])
        self.text("%d/%d" % (me["hp"], me["max_hp"]), x + w - 7, y + 3, align="right")

        # Your moves against it.
        y += 26
        self.text("Your moves vs %s" % (nick or name), x + 2, y, TAB_TEXT, TAB_SHADOW)
        y += 16
        mw, mh = (w - PAD) // 2, (H - PAD - y - PAD) // 2
        scored = []
        for i, move in enumerate(me["moves"]):
            info = self.rom.move_info(move) if move else None
            if info and info["power"]:
                stab = 1.5 if info["type"] in my_types else 1
                scored.append((info["power"] * stab * typechart.multiplier(info["type"], foe_types), i))
        best = max(scored)[1] if scored and max(scored)[0] > 0 else None
        for i, move in enumerate(me["moves"]):
            mx, my = x + (i % 2) * (mw + PAD), y + (i // 2) * (mh + PAD)
            if not move:
                self.frame(mx, my, mw, mh, fill=WIN_DIM, line=None)
                continue
            info = self.rom.move_info(move)
            self.frame(mx, my, mw, mh, line=None if i == best else LINE)
            if i == best:
                self.outline(mx + 2, my + 2, mw - 4, mh - 4, BEST, 2)
            right = mx + mw - 6
            if info:
                right -= self.pill(info["type"], right - self.text_width(info["type"].upper()) - 6, my + 5,
                                   TYPE_COLORS.get(info["type"], MUTED)) + 2
            nw = self.text(self.fit(self.rom.move_name(move), right - mx - 8 - (30 if i == best else 0)), mx + 6, my + 3)
            if i == best:
                self.pill("Best", mx + 9 + nw, my + 5, BEST)
            if not info:
                continue
            if info["power"]:
                label, color = effect_label(typechart.multiplier(info["type"], foe_types))
                if info["type"] in my_types and color is not MUTED:
                    label += " STAB"
            else:
                label, color = "Status move", MUTED
            self.text(self.fit(label, mw - 12), mx + 6, my + 18, color, None)
            parts = ["PP%d/%d" % (me["pp"][i], info["pp"])]
            if info["power"] > 1:
                parts.append("Pow%d" % info["power"])
            if info["acc"] and info["acc"] < 100:  # 100 is the norm; only show misses
                parts.append("Acc%d" % info["acc"])
            if info["priority"]:
                parts.append("Pri%+d" % info["priority"])
            self.text(self.fit(" ".join(parts), mw - 12), mx + 6, my + mh - 19, MUTED, None)

    def stage_chips(self, stages, right, y):
        """Non-zero stat stages, right-aligned, e.g. 'Atk+1 Spe-2'."""
        x = right
        for k in reversed(range(1, 8)):
            v = stages[k]
            if v:
                x -= self.text("%s%+d" % (STAGE_NAMES[k], v), x, y, BEST if v > 0 else RED, None, "right") + 4

    # ---------- bag ----------

    def draw_bag(self, snap):
        bag = snap.get("bag")
        if bag is None:
            self.message("Looking for the bag...")
            return
        x, w = PAD, W - 2 * PAD
        sel = min(self.ui.get("pocket", 0), len(bag) - 1)
        name, items = bag[sel]

        # Pocket switcher, like the bag's own pocket title.
        y = TAB_H + PAD
        self.frame(x, y, w, 24, line=None)
        self.arrow(x + 8, y + 8, "l", INK if sel else LINE)
        self.arrow(x + w - 12, y + 8, "r", INK if sel < len(bag) - 1 else LINE)
        self.text(name, W // 2, y + 3, align="center")
        self.text("%d/%d" % (sel + 1, len(bag)), x + w - 24, y + 3, MUTED, None, "right")

        # Items.
        y += 28
        per_page = BAG_ROWS
        pages = max(1, (len(items) + per_page - 1) // per_page)
        page = min(self.ui.get("page", 0), pages - 1)
        lh = 16 * BAG_ROWS + 8
        self.frame(x, y, w, lh)
        chosen = self.ui.get("item")
        if not items:
            self.text("This pocket is empty", W // 2, y + lh // 2 - 8, MUTED, None, "center")
        for k, (item, qty) in enumerate(items[page * per_page:(page + 1) * per_page]):
            ry = y + 4 + k * 16
            if item == chosen:
                self.rect(x + 4, ry, w - 8, 16, WIN_DIM)
                self.arrow(x + 7, ry + 5, "r", INK)
            self.text(self.fit(self.rom.item_name(item), w - 70), x + 16, ry)
            if "key" not in name.lower() or qty > 1:
                self.text("×%d" % qty, x + w - 10, ry, align="right")
        if pages > 1:
            if page:
                self.arrow(x + w - 16, y + 8, "u", MUTED)
            self.text("%d/%d" % (page + 1, pages), x + w - 22, y + lh - 20, MUTED, None, "right")
            if page < pages - 1:
                self.arrow(x + w - 16, y + lh - 14, "d", MUTED)
        self._bag_list = (y + 4, per_page, page, pages)

        # What the chosen item does.
        y += lh + 4
        hgt = H - PAD - y
        self.frame(x, y, w, hgt)
        if chosen and any(item == chosen for item, _ in items):
            for n, line in enumerate(self.wrap(self.rom.item_description(chosen), w - 16, 2)):
                self.text(line, x + 8, y + 4 + n * 15)
        else:
            self.text("Tap an item to see what it does", x + 8, y + 4, MUTED, None)

    def bag_tap(self, x, y, snap):
        bag = snap.get("bag")
        if not bag:
            return
        sel = min(self.ui.get("pocket", 0), len(bag) - 1)
        top = TAB_H + PAD
        if top <= y < top + 24:
            sel = max(0, sel - 1) if x < W // 2 else min(len(bag) - 1, sel + 1)
            self.ui.update(pocket=sel, page=0, item=None)
            return
        list_top, per_page, page, pages = getattr(self, "_bag_list", (0, BAG_ROWS, 0, 1))
        if list_top <= y < list_top + per_page * 16:
            if x > W - 60 and pages > 1:  # the page column at the right
                self.ui["page"] = (page + 1) % pages if y >= list_top + per_page * 8 else max(0, page - 1)
                return
            k = page * per_page + (y - list_top) // 16
            items = bag[sel][1]
            if k < len(items):
                self.ui["item"] = items[k][0]

    def bag_step(self, step, snap):
        """Stick up/down: the previous/next item of the pocket, turning pages as needed."""
        bag = snap.get("bag")
        if not bag or not step:
            return
        items = bag[min(self.ui.get("pocket", 0), len(bag) - 1)][1]
        if not items:
            return
        ids = [item for item, _ in items]
        cur = self.ui.get("item")
        k = (ids.index(cur) + step) % len(ids) if cur in ids else (0 if step > 0 else len(ids) - 1)
        self.ui["item"] = ids[k]
        self.ui["page"] = k // BAG_ROWS

    # ---------- map ----------

    MAP_MODES = ("Map", "Wild")

    def draw_map(self, snap):
        loc = snap.get("location")
        if not loc and self.args.debug_mapsec is not None:
            loc = {"mapsec": self.args.debug_mapsec, "group": None, "num": None}
        if not loc:
            self.message("Looking for your location...")
            return
        x, w = PAD, W - 2 * PAD
        y = TAB_H + PAD
        name = self.rom.mapsec_name(loc["mapsec"]) if loc["mapsec"] is not None else None
        self.frame(x, y, w, 24, line=None)
        self.text(self.fit(name or "Unknown area", w - 100), x + 8, y + 3)
        mode = self.ui.get("map_mode", "Map")
        for i, m in enumerate(self.MAP_MODES):
            self.chip(m, x + w - 4 - (len(self.MAP_MODES) - i) * 44, y + 4, 42, 16, m == mode)
        if mode == "Map":
            self.draw_region(loc, y + 28)
        else:
            self.draw_wild(loc, y + 28)

    def draw_region(self, loc, y0):
        if not hasattr(self.rom, "_region_map"):
            if not getattr(self, "_map_thread", None):
                self._map_thread = threading.Thread(target=self._build_region_map, daemon=True)
                self._map_thread.start()
            self.message("Drawing the map...", y0, H - y0)
            return
        m = self.rom.region_map()
        if not m:
            self.message("No region map for this game", y0, H - y0)
            return
        sec = m["sections"].get(loc["mapsec"])
        image = sec[0] if sec else 0
        iw, ih, _ = m["images"][image]
        mx, my = (W - iw) // 2, y0 + (H - PAD - y0 - ih) // 2
        self.rect(mx - 2, my - 2, iw + 4, ih + 4, INK)
        tex = self.map_texture(image, m)
        if tex:
            sdl.RenderCopy(self.ren, tex, None, ctypes.byref(sdl.Rect(mx, my, iw, ih)))
        if sec:
            _, sx, sy, sw, sh = sec
            self.rect(mx + sx, my + sy, sw, sh, RED, 130)
            if int(time.monotonic() * 2) % 2 == 0:  # blinking frame
                self.outline(mx + sx - 1, my + sy - 1, sw + 2, sh + 2, WHITE, 1)
                self.outline(mx + sx - 2, my + sy - 2, sw + 4, sh + 4, INK, 1)
        else:
            self.text("Not shown on the map", W // 2, my + ih - 18, WHITE, INK, "center")

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

    def wild_modes(self, loc):
        """{mode: entries}, with fishing split per rod."""
        wild = self.rom.wild_encounters(loc["group"], loc["num"]) if loc["group"] is not None else {}
        out = {}
        for method, entries in wild.items():
            if method == "Fishing":
                for rod in ("Old Rod", "Good Rod", "Super Rod"):
                    sub = [e for e in entries if e[4] == rod]
                    if sub:
                        out[rod] = sub
            else:
                out[method] = entries
        return out

    def draw_wild(self, loc, y0):
        x, w = PAD, W - 2 * PAD
        modes = self.wild_modes(loc)
        if not modes:
            self.message("No wild Pokémon here", y0, H - y0)
            return
        names = list(modes)
        sel = self.ui.get("method") if self.ui.get("method") in names else names[0]
        cw = w // max(len(names), 4)
        for i, m in enumerate(names):
            self.chip(WILD_LABELS.get(m, m), x + i * cw, y0, cw - 2, 18, m == sel)
        y = y0 + 22
        hgt = H - PAD - y
        self.frame(x, y, w, hgt)
        entries = modes[sel]
        cellw, cellh = (w - 8) // WILD_COLS, (hgt - 8) // WILD_ROWS
        for k, (species, lo, hi, pct, _) in enumerate(entries[:WILD_COLS * WILD_ROWS]):
            ex, ey = x + 4 + (k % WILD_COLS) * cellw, y + 4 + (k // WILD_COLS) * cellh
            self.sprite(species, ex, ey + (cellh - 32) // 2)
            self.text(self.fit(self.rom.species_name(species), cellw - 36), ex + 34, ey + 2)
            lv = "Lv%d" % lo if lo == hi else "Lv%d-%d" % (lo, hi)
            self.text("%s %d%%" % (lv, pct), ex + 34, ey + 17, MUTED, None)
        if len(entries) > WILD_COLS * WILD_ROWS:
            self.text("+%d" % (len(entries) - WILD_COLS * WILD_ROWS), x + w - 8, y + hgt - 18, MUTED, None, "right")
        self._wild_chips = (y0, cw, names)

    def wild_step(self, step, snap):
        """Stick up/down on Wild: the previous/next way of finding Pokemon."""
        loc = snap.get("location")
        if self.ui.get("map_mode", "Map") != "Wild" or not loc or loc.get("group") is None or not step:
            return
        names = list(self.wild_modes(loc))
        if names:
            cur = self.ui.get("method")
            k = names.index(cur) if cur in names else 0
            self.ui["method"] = names[(k + step) % len(names)]

    def map_tap(self, x, y, snap):
        top = TAB_H + PAD
        if top <= y < top + 24 and x >= W - PAD - 4 - len(self.MAP_MODES) * 44:
            i = (x - (W - PAD - 4 - len(self.MAP_MODES) * 44)) // 44
            self.ui["map_mode"] = self.MAP_MODES[min(i, len(self.MAP_MODES) - 1)]
            return
        chips = getattr(self, "_wild_chips", None)
        if self.ui.get("map_mode", "Map") == "Wild" and chips:
            y0, cw, names = chips
            if y0 <= y < y0 + 18:
                i = (x - PAD) // cw
                if 0 <= i < len(names):
                    self.ui["method"] = names[i]

    # ---------- settings ----------

    def draw_settings(self, snap):
        x, w = PAD, W - 2 * PAD
        y = TAB_H + PAD
        mode = snap.get("party_mode", "auto")
        in_use = snap.get("learned") or snap.get("party_addr")
        rows = [("auto", "Auto", "using 0x%08X" % in_use if in_use else "")]
        for c in snap.get("candidates", [])[:3]:
            names = (snap.get("previews") or {}).get(c)
            preview = (", ".join(self.rom.species_name(s) for s in names[:2]) + (" +%d" % (len(names) - 2)
                       if len(names) > 2 else "")) if names else "empty now"
            rows.append(("%08X" % c, "0x%08X" % c, preview))
        hgt = 22 + len(rows) * 18 + 4
        self.frame(x, y, w, hgt)
        self.text("Party data", x + 8, y + 3)
        self.text("Auto learns the live copy", x + w - 8, y + 3, MUTED, None, "right")
        self._settings_rows = []
        for i, (key, label, sub) in enumerate(rows):
            ry = y + 22 + i * 18
            on = mode == key
            if on:
                self.rect(x + 4, ry, w - 8, 18, WIN_DIM)
            if on:
                self.arrow(x + 7, ry + 6, "r", INK)
            self.text(label, x + 16, ry + 1)
            self.text(self.fit(sub, w - 130), x + w - 8, ry + 1, MUTED, None, "right")
            self._settings_rows.append((ry, key))
        y += hgt + 4
        bw = (w - PAD) // 2
        self._settings_buttons = []
        for i, (label, action) in enumerate((("Scan RAM again", "rescan_party"), ("Forget addresses", "reset"))):
            bx = x + i * (bw + PAD)
            self.chip(label, bx, y, bw, 20, True)
            self._settings_buttons.append((bx, y, bw, action))
        y += 24
        hgt = H - PAD - y
        self.frame(x, y, w, hgt)
        self.text("Found in RAM", x + 8, y + 3)
        self.text("CRC " + self.rom.crc, x + w - 8, y + 3, MUTED, None, "right")
        found = snap.get("found", {})
        for i, (key, label, hint) in enumerate((("gmain", "Battle flag", "on start"),
                                                ("battle_mons", "Battle", "in your next battle"),
                                                ("bag_pockets", "Bag", "when you open Bag"),
                                                ("map_header", "Location", "when you open Map"))):
            ry = y + 19 + i * 15
            self.text(label, x + 8, ry, MUTED, None)
            self.text("0x%08X" % found[key] if key in found else hint, x + 100, ry,
                      INK if key in found else MUTED, SHADOW if key in found else None)

    def settings_tap(self, x, y, snap):
        if not self.mem:
            return
        for ry, key in getattr(self, "_settings_rows", []):
            if ry <= y < ry + 18:
                self.mem.set_party_mode(key)
                return
        for bx, by, bw, action in getattr(self, "_settings_buttons", []):
            if bx <= x < bx + bw and by <= y < by + 20:
                self.mem.request(action)
                return

    def on_screen_tap(self, view, x, y):
        snap = self.mem.snapshot() if self.mem else {}
        {"bag": self.bag_tap, "map": self.map_tap, "settings": self.settings_tap}.get(
            view, lambda *a: None)(x, y, snap)
