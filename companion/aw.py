# SPDX-License-Identifier: GPL-2.0-or-later
"""Advance Wars 2 companion: the armies, a damage calculator that follows the
game's cursor, your units' supplies and dangers, and every enemy's reach on the map.

The game itself shows one damage estimate without luck. Here: the damage
range with luck, the chance to destroy, the counterattack, which of your units
can hit the unit under the cursor this turn, and which enemies can hit yours.
"""

import aw_data as aw
from base import BaseApp, log
from ra import RetroArch
from theme import *  # noqa: F401,F403 - geometry, font, colours

ARMY_COLORS = ((216, 104, 56), (64, 104, 184), (64, 144, 80), (200, 168, 40))
LIST_ROWS = 11

# Map colours by terrain type (low 5 bits of the map byte).
TERRAIN_COLORS = {1: (190, 214, 150), 2: (110, 150, 214), 3: (166, 140, 104), 4: (120, 168, 104),
                  5: (200, 200, 196), 7: (100, 140, 200), 9: (100, 140, 200), 12: (200, 200, 196),
                  13: (220, 206, 160), 15: (120, 124, 132), 16: (120, 124, 132), 19: (90, 120, 170)}
PROPERTY_TYPES = aw.PROPERTY_TYPES


class AdvanceWarsApp(BaseApp):
    TABS = ["Army", "Attack", "Units", "Map"]
    VIEWS = ["army", "attack", "units", "map", "settings"]

    def __init__(self, args):
        super().__init__(args)
        self.rom = None
        self.ui["me"] = 0                   # whose side the views take: army index

    def load_game(self):
        self.rom = aw.AWRom(self.args.rom)
        log("ROM %s (%s): Advance Wars 2" % (self.rom.title, self.rom.code))
        self.ready = True
        self.mem = aw.AWMemory(RetroArch(port=self.args.port), self.rom, self.dirty.set)
        self.mem.view = self.view
        self.mem.start()
        self.dirty.set()

    # ---------- helpers ----------

    def me(self, snap):
        armies = [a["index"] for a in snap.get("armies") or []]
        m = self.ui.get("me", 0)
        return m if m in armies or not armies else armies[0]

    def unit_at(self, snap, x, y):
        return next((u for u in snap.get("units") or [] if (u["x"], u["y"]) == (x, y)), None)

    def army_name(self, a):
        return aw.ARMY_NAMES[a + 1] if a + 1 < len(aw.ARMY_NAMES) else "Army %d" % (a + 1)

    def terrain_at(self, snap, x, y):
        return snap["map"]["terrain"][y][x]

    def threats_on(self, snap, u):
        """Enemies that can hit u on their next move: [(enemy, max damage)]."""
        out = []
        threats = snap.get("threats") or {}
        tb = self.terrain_at(snap, u["x"], u["y"])
        for e in snap["units"]:
            if e["army"] == u["army"] or (u["x"], u["y"]) not in threats.get((e["army"], e["slot"]), ()):
                continue
            r = aw.damage_range(self.rom, e, u, tb)
            if r:
                out.append((e, r[0][1]))
        return out

    def hp_text(self, u):
        return str(aw.display_hp(u["hp"]))

    # ---------- views ----------

    def draw_view(self, view, snap):
        if snap.get("error"):
            self.message("Game data error, see the log")
            return
        if not snap.get("map") or not snap.get("units"):
            self.message("Waiting for a battle map...")
            return
        if snap.get("fog"):
            # Under fog the companion knows no more than you: enemies outside your vision stay hidden.
            me = self.me(snap)
            seen = (snap.get("visible") or {}).get(me, set())
            snap = dict(snap)
            snap["units"] = [u for u in snap["units"] if u["army"] == me or (u["x"], u["y"]) in seen]
            snap["armies"] = [dict(a, units=None, value=None) if a["index"] != me else a
                              for a in snap.get("armies") or []]
        {"army": self.draw_army, "attack": self.draw_attack, "units": self.draw_units,
         "map": self.draw_map}[view](snap)

    # Army

    def draw_army(self, snap):
        x, w = PAD, W - 2 * PAD
        y = TAB_H + PAD
        self.frame(x, y, w, 22, line=None)
        cur = snap.get("current")
        self.text("Day %d" % snap.get("day", 0), x + 8, y + 3)
        if cur is not None:
            self.text(self.army_name(cur) + "'s turn", x + w - 8, y + 3, MUTED, None, "right")
        y += 26
        armies = snap.get("armies") or []
        me = self.me(snap)
        ah = 40
        for a in armies[:4]:
            self.frame(x, y, w, ah)
            c = ARMY_COLORS[a["index"] % 4]
            self.rect(x + 6, y + 6, 6, ah - 12, c)
            name = self.army_name(a["index"]) + (" (you)" if a["index"] == me else "")
            self.text(name, x + 18, y + 3)
            right = x + w - 6
            if a["power"]:
                right -= self.tag_right("SUPER" if a["power"] == 2 else "POWER", right, y + 3, *TAG_AMBER) + 4
            self.text(a["co"]["name"] if a["co"] else "?", right - 2, y + 3, MUTED, None, "right")
            line = "G %d" % a["funds"]
            if a["co"] and not a["power"]:
                stars = a["meter"] / float(aw.STAR)
                line += "  stars %.1f" % stars
                if a["co"]["scop"] and stars >= a["co"]["scop"]:
                    line += " Super ready"
                elif a["co"]["cop"] and stars >= a["co"]["cop"]:
                    line += " Power ready"
            self.text(line, x + 18, y + 19, MUTED, None)
            if a["units"] is not None:
                self.text("%d units · worth %d" % (a["units"], a["value"]), x + w - 8, y + 19, INK, None, "right")
            else:
                self.text("hidden by fog", x + w - 8, y + 19, MUTED, None, "right")
            y += ah + 4
        # Unit counts, mine against the first other army.
        others = [a for a in armies if a["index"] != me]
        if not others or y > H - 40:
            return
        foe = others[0]["index"]
        counts = {}
        for u in snap["units"]:
            if u["army"] in (me, foe):
                counts.setdefault(u["unit"]["name"], [0, 0])[0 if u["army"] == me else 1] += 1
        hgt = H - PAD - y
        self.frame(x, y, w, hgt)
        rows = sorted(counts.items(), key=lambda kv: -(kv[1][0] + kv[1][1]))
        per_col = max(1, (hgt - 8) // 16)
        cw = (w - 8) // 2
        for i, (name, (mine, theirs)) in enumerate(rows[:per_col * 2]):
            cx = x + 4 + (i // per_col) * cw
            ry = y + 4 + (i % per_col) * 16
            self.text(self.fit(name, 70), cx + 4, ry, INK, None)
            self.text("%d" % mine, cx + 96, ry, ARMY_COLORS[me % 4], None, "right")
            self.text("?" if snap.get("fog") else "%d" % theirs, cx + 126, ry, ARMY_COLORS[foe % 4], None, "right")

    # Attack: follows the game's cursor

    def draw_attack(self, snap):
        cx, cy = snap.get("cursor", (0, 0))
        mp = snap["map"]
        x, w = PAD, W - 2 * PAD
        y = TAB_H + PAD
        me = self.me(snap)
        target = self.unit_at(snap, cx, cy) if cx < mp["w"] and cy < mp["h"] else None
        if not target:
            self.frame(x, y, w, 40)
            if cx < mp["w"] and cy < mp["h"]:
                t = self.rom.terrain(self.terrain_at(snap, cx, cy))
                self.text("%s · %d star%s" % (t["name"], t["stars"], "" if t["stars"] == 1 else "s"), x + 8, y + 3)
            self.text("Put the cursor on a unit", x + 8, y + 19, MUTED, None)
            return
        tb = self.terrain_at(snap, cx, cy)
        tt = self.rom.terrain(tb)
        self.frame(x, y, w, 38)
        c = ARMY_COLORS[target["army"] % 4]
        self.rect(x + 6, y + 6, 6, 26, c)
        self.text("%s  HP %s" % (target["unit"]["name"], self.hp_text(target)), x + 18, y + 3)
        self.text("%s %d def" % (tt["name"], 0 if target["unit"]["category"] in (2, 3) else tt["stars"]),
                  x + w - 8, y + 3, MUTED, None, "right")
        co = target["co"]["name"] if target["co"] else ""
        self.text(self.fit("%s · %s" % (self.army_name(target["army"]), co), w - 30), x + 18, y + 19, MUTED, None)
        y += 42
        hgt = H - PAD - y
        self.frame(x, y, w, hgt)
        rows = []
        threats = snap.get("threats") or {}
        if target["army"] != me:
            title = "Your units that can hit it this turn"
            for u in snap["units"]:
                if u["army"] != me or u["moved"] or (cx, cy) not in threats.get((u["army"], u["slot"]), ()):
                    continue
                r = aw.damage_range(self.rom, u, target, tb)
                if not r:
                    continue
                (lo, hi), _ = r
                kill = aw.kill_chance(self.rom, u, target, tb)
                counter = None
                if not u["unit"]["indirect"] and not target["unit"]["indirect"]:
                    left = max(0, target["hp"] - lo)
                    if left:
                        cr = aw.damage_range(self.rom, target, u, self.terrain_at(snap, u["x"], u["y"]),
                                             att_hp=left)
                        counter = cr[0] if cr else None
                rows.append((hi, u, lo, hi, kill, counter))
            rows.sort(key=lambda r: -r[0])
        else:
            title = "Enemies that can hit it next turn"
            for e, hi in self.threats_on(snap, target):
                r = aw.damage_range(self.rom, e, target, tb)
                (lo, hi), _ = r
                kill = aw.kill_chance(self.rom, e, target, tb)
                rows.append((hi, e, lo, hi, kill, None))
            rows.sort(key=lambda r: -r[0])
        self.text(title, x + 8, y + 3, MUTED, None)
        if not rows:
            self.text("None", x + 8, y + 21)
        for k, (_, u, lo, hi, kill, counter) in enumerate(rows[:(hgt - 24) // 16]):
            ry = y + 21 + k * 16
            self.rect(x + 8, ry + 4, 5, 8, ARMY_COLORS[u["army"] % 4])
            self.text(self.fit("%s %s" % (u["unit"]["name"], self.hp_text(u)), 92), x + 17, ry)
            self.text("%d-%d%%" % (lo, hi), x + 170, ry, align="right")
            right = x + w - 6
            if kill >= 1:
                right -= self.tag_right("destroys", right, ry, *TAG_GREEN) + 3
            elif kill > 0:
                right -= self.tag_right("kill %d%%" % round(kill * 100), right, ry, *TAG_AMBER) + 3
            if counter:
                self.text("back %d-%d" % counter, right - 2, ry, RED if counter[1] >= 50 else MUTED, None, "right")
        if target["army"] == me and rows:
            total = sum(r[3] for r in rows)
            ty = y + hgt - 20
            c = RED if total >= target["hp"] else AMBER
            self.text("Together up to %d%% of its %d%%" % (total, target["hp"]), x + 8, ty, c, None)

    # Units: supplies and danger

    def draw_units(self, snap):
        me = self.me(snap)
        mine = [u for u in snap["units"] if u["army"] == me]
        x, w = PAD, W - 2 * PAD
        y = TAB_H + PAD
        self.frame(x, y, w, 22, line=None)
        waiting = sum(1 for u in mine if not u["moved"])
        self.text("%s · %d units" % (self.army_name(me), len(mine)), x + 8, y + 3)
        self.text("%d not moved" % waiting, x + w - 8, y + 3, MUTED, None, "right")
        y += 26
        lh = H - PAD - y
        self.frame(x, y, w, lh)
        sel = min(self.ui.get("unit_sel", 0), max(0, len(mine) - 1))
        page = sel // LIST_ROWS
        for k, u in enumerate(mine[page * LIST_ROWS:(page + 1) * LIST_ROWS]):
            ry = y + 4 + k * 16
            ut = u["unit"]
            c = MUTED if u["moved"] else INK
            self.text(self.fit(ut["name"], 62), x + 8, ry, c, None)
            self.text(self.hp_text(u), x + 84, ry, c, None, "right")
            self.bar(x + 88, ry + 6, 26, u["hp"] / 100.0, self.hp_color(u["hp"], 100))
            daily = aw.DAILY_FUEL.get(ut["type"], 0)
            low_fuel = (daily and u["fuel"] <= daily * 2) or u["fuel"] <= ut["fuel"] // 5
            self.text("F%d" % u["fuel"], x + 120, ry, RED if low_fuel else MUTED, None)
            if ut["ammo"]:
                self.text("A%d" % u["ammo"], x + 152, ry, RED if u["ammo"] == 0 else MUTED, None)
            hits = self.threats_on(snap, u)
            right = x + w - 6
            if daily and u["fuel"] < daily:
                right -= self.tag_right("crashes", right, ry, *TAG_RED) + 3
            if hits:
                total = sum(h for _, h in hits)
                if total >= u["hp"]:
                    self.tag_right("can die", right, ry, *TAG_RED)
                else:
                    self.tag_right("%d hit" % len(hits), right, ry, *TAG_AMBER)
        pages = max(1, (len(mine) + LIST_ROWS - 1) // LIST_ROWS)
        if page:
            self.arrow(x + w - 12, y + 3, "u", INK)
        if page < pages - 1:
            self.arrow(x + w - 12, y + lh - 8, "d", INK)
        self._list = (y + 4, page, len(mine))

    # Map

    def draw_map(self, snap):
        mp = snap["map"]
        w, h, terrain = mp["w"], mp["h"], mp["terrain"]
        me = self.me(snap)
        info_h = 38
        avail_w, avail_h = W - 2 * PAD - 4, H - TAB_H - 2 * PAD - info_h - 8
        t = max(4, min(16, avail_w // w, avail_h // h))
        mw, mh = t * w, t * h
        ox, oy = (W - mw) // 2, TAB_H + PAD + 2 + (avail_h - mh) // 2
        self.rect(ox - 2, oy - 2, mw + 4, mh + 4, INK)
        for yy in range(h):
            row = terrain[yy]
            for xx in range(w):
                tb = row[xx]
                kind = tb & 0x1F
                c = TERRAIN_COLORS.get(kind, (190, 214, 150))
                owner = tb >> 5
                if kind in PROPERTY_TYPES:
                    c = ARMY_COLORS[(owner - 1) % 4] if owner else (214, 214, 214)
                    c = tuple((v + 2 * 230) // 3 for v in c)
                self.rect(ox + xx * t, oy + yy * t, t, t, c)
                if kind in PROPERTY_TYPES:
                    self.outline(ox + xx * t + 1, oy + yy * t + 1, t - 2, t - 2, MUTED)
        threats = snap.get("threats") or {}
        chosen = self.ui.get("map_enemy")
        danger = set()
        for u in snap["units"]:
            if u["army"] != me:
                danger |= threats.get((u["army"], u["slot"]), set())
        for (xx, yy) in danger:
            self.rect(ox + xx * t, oy + yy * t, t, t, (210, 70, 60), 80)
        if chosen and chosen in threats:
            for (xx, yy) in threats[chosen]:
                self.rect(ox + xx * t, oy + yy * t, t, t, (232, 176, 64), 150)
        for u in snap["units"]:
            c = ARMY_COLORS[u["army"] % 4]
            if u["moved"]:
                c = tuple((v + 2 * m) // 3 for v, m in zip(c, MUTED))
            px, py = ox + u["x"] * t, oy + u["y"] * t
            self.rect(px + 2, py + 2, t - 4, t - 4, c)
            if aw.display_hp(u["hp"]) < 10 and t >= 8:
                self.rect(px + t - 5, py + t - 5, 4, 4, WHITE)
            if (u["army"], u["slot"]) == chosen:
                self.outline(px, py, t, t, INK, 2)
        cx, cy = snap.get("cursor", (0, 0))
        if cx < w and cy < h:
            self.outline(ox + cx * t, oy + cy * t, t, t, WHITE)
        self._map_geom = (ox, oy, t, w, h)
        y = H - PAD - info_h
        self.frame(PAD, y, W - 2 * PAD, info_h)
        e = next((u for u in snap["units"] if (u["army"], u["slot"]) == chosen), None)
        if e:
            ut = e["unit"]
            self.text("%s HP %s · %s" % (ut["name"], self.hp_text(e), self.army_name(e["army"])), PAD + 8, y + 3)
            rng = "%d-%d" % (ut["min"], ut["max"] + e["mod"][3]) if ut["indirect"] else "move %d + 1" % (
                ut["move"] + e["mod"][2])
            self.text("Gold: where it can fire (%s)" % rng, PAD + 8, y + 19, MUTED, None)
        else:
            self.text("Red: where enemies can fire next turn", PAD + 8, y + 3, INK, None)
            self.text("Tap an enemy for its own reach", PAD + 8, y + 19, MUTED, None)

    def draw_settings(self, snap):
        x, w = PAD, W - 2 * PAD
        y = TAB_H + PAD
        self.frame(x, y, w, 44)
        me = self.me(snap)
        self.text("Your side", x + 8, y + 3, MUTED, None)
        self.text(self.army_name(me), x + w - 8, y + 3, ARMY_COLORS[me % 4], None, "right")
        self.text("Tap to switch armies", x + 8, y + 21, MUTED, None)
        self._me_row = (y, 44)
        y += 48
        self.frame(x, y, w, 46)
        self.text("Game", x + 8, y + 3, MUTED, None)
        self.text(self.rom.title if self.rom else "-", x + w - 8, y + 3, INK, None, "right")
        self.text("RetroArch", x + 8, y + 21, MUTED, None)
        self.text("connected" if snap.get("connected") else "not answering", x + w - 8, y + 21, INK, None,
                  "right")

    # ---------- input ----------

    def stick_view(self, view, action, snap):
        step = 1 if action == "down" else -1 if action == "up" else 0
        if view == "units":
            n = sum(1 for u in snap.get("units") or [] if u["army"] == self.me(snap))
            if n:
                self.ui["unit_sel"] = (min(self.ui.get("unit_sel", 0), n - 1) + step * LIST_ROWS) % (
                    ((n + LIST_ROWS - 1) // LIST_ROWS) * LIST_ROWS)
        elif view == "map":
            me = self.me(snap)
            foes = [(u["army"], u["slot"]) for u in snap.get("units") or [] if u["army"] != me]
            if action == "press" or not foes:
                self.ui["map_enemy"] = None
                return
            cur = self.ui.get("map_enemy")
            k = (foes.index(cur) + step) % len(foes) if cur in foes else 0
            self.ui["map_enemy"] = foes[k]
        elif view == "settings" and action == "press":
            self.cycle_me(snap)

    def cycle_me(self, snap):
        armies = [a["index"] for a in snap.get("armies") or []]
        if armies:
            cur = self.me(snap)
            self.ui["me"] = armies[(armies.index(cur) + 1) % len(armies)] if cur in armies else armies[0]

    def tap_view(self, view, x, y):
        snap = self.mem.snapshot() if self.mem else {}
        if view == "settings":
            ry, rh = getattr(self, "_me_row", (0, 0))
            if ry <= y < ry + rh:
                self.cycle_me(snap)
        elif view == "units":
            top, page, n = getattr(self, "_list", (0, 0, 0))
            pages = max(1, (n + LIST_ROWS - 1) // LIST_ROWS)
            if pages > 1 and x >= W - PAD - 22:
                k = (y - top) // 16
                page = (page + (1 if k >= LIST_ROWS // 2 else -1)) % pages
                self.ui["unit_sel"] = page * LIST_ROWS
        elif view == "map":
            geom = getattr(self, "_map_geom", None)
            if not geom:
                return
            ox, oy, t, w, h = geom
            tx, ty = (x - ox) // t, (y - oy) // t
            u = self.unit_at(snap, tx, ty) if 0 <= tx < w and 0 <= ty < h else None
            if u and u["army"] != self.me(snap):
                key = (u["army"], u["slot"])
                self.ui["map_enemy"] = None if self.ui.get("map_enemy") == key else key
            else:
                self.ui["map_enemy"] = None
