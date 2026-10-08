# SPDX-License-Identifier: GPL-2.0-or-later
"""Fire Emblem 7 companion: your units, the battle you're choosing, the enemies and the map.

What it adds to the game: who can be reached and killed on the enemy phase,
real hit rates (the game rolls two numbers and averages them), kill chances,
hidden growth rates, and every enemy's range on the map at once.
"""

import fe_data as fe
from base import BaseApp, log
from ra import RetroArch
from theme import *  # noqa: F401,F403 - geometry, font, colours

AMBER = (176, 120, 16)
BLUE_UNIT, RED_UNIT, GREEN_UNIT = (64, 104, 184), (192, 64, 56), (64, 144, 80)
LIST_ROWS = 11
ENEMY_ROWS = 7

# Map colours by terrain id (FE7 ids; anything else draws as plain).
TERRAIN_COLORS = {}
for ids, c in (((1, 2, 0x13, 0x14, 0x17, 0x18, 0x2F, 0x39), (206, 210, 196)),           # plain, road, floor, bridge
               ((0x0C, 0x0D), (150, 178, 132)),                                          # forest, thicket
               ((0x0E, 0x0F), (214, 202, 160)),                                          # sand, desert
               ((0x10, 0x15, 0x16, 0x3B, 0x3D), (118, 150, 196)),                         # river, sea, lake
               ((0x11, 0x12, 0x26, 0x32), (150, 138, 120)),                              # mountain, peak, cliff
               ((0x19, 0x1A, 0x1B, 0x1D, 0x22, 0x33), (92, 100, 112)),                    # fence, walls, pillar, roof
               ((3, 4, 5, 6, 7, 8, 9, 0x0A, 0x0B, 0x1E, 0x1F, 0x20, 0x21, 0x23, 0x24, 0x25),
                (214, 184, 132))):                                                        # buildings, gates, doors
    for t in ids:
        TERRAIN_COLORS[t] = c


def pct(p):
    return "%d%%" % round(p * 100)


class FireEmblemApp(BaseApp):
    TABS = ["Units", "Battle", "Enemies", "Map"]
    VIEWS = ["units", "battle", "enemies", "map", "settings"]

    def __init__(self, args):
        super().__init__(args)
        self.rom = None
        self.detail = args.detail    # slot of the blue unit whose page is open

    def load_game(self):
        self.rom = fe.FERom(self.args.rom)
        log("ROM %s (%s): FE7 tables text 0x%X items 0x%X classes 0x%X" % (
            self.rom.title, self.rom.code, self.rom.text_table, self.rom.items, self.rom.classes))
        self.ready = True
        self.mem = fe.FEMemory(RetroArch(port=self.args.port), self.rom, self.dirty.set)
        self.mem.view = self.view
        self.mem.start()
        self.dirty.set()

    def on_tab_change(self):
        self.detail = None

    # ---------- helpers ----------

    def units(self, snap, faction):
        return [u for u in snap.get("units") or [] if u["faction"] == faction and not u["rescued"]]

    def dangers(self, snap):
        """{blue slot: (enemies that can reach it, most damage they can do)}."""
        threats = snap.get("threats") or {}
        reds = {u["slot"]: u for u in self.units(snap, "red")}
        terrain = (snap.get("map") or {}).get("terrain")
        out = {}
        for u in self.units(snap, "blue"):
            pos = (u["x"], u["y"])
            mine, _ = fe.equipped(self.rom, u)
            tid = terrain[u["y"]][u["x"]] if terrain else 1
            n, total = 0, 0
            for slot, tiles in threats.items():
                e = reds.get(slot)
                if e is None or pos not in tiles:
                    continue
                n += 1
                best = 0
                for it in fe.weapons(self.rom, e):
                    d = fe.damage(self.rom, e, it, u, tid, mine)
                    best = max(best, d * fe.strikes(self.rom, e, it, u, mine))
                total += best
            out[u["slot"]] = (n, total)
        return out

    def header(self, snap, y):
        phase = {0: "Player phase", 0x40: "Other phase", 0x80: "Enemy phase"}.get(snap.get("phase"), "")
        self.frame(PAD, y, W - 2 * PAD, 22, line=None)
        self.text("Turn %d" % snap.get("turn", 0), PAD + 8, y + 3)
        self.text(phase, W - PAD - 8, y + 3, MUTED, None, "right")
        if snap.get("vision"):
            self.text("Fog", W // 2, y + 3, AMBER, None, "center")

    # ---------- views ----------

    def draw_view(self, view, snap):
        if snap.get("error"):
            self.message("Game data error, see the log")
            return
        if not snap.get("map") or not snap.get("units"):
            self.message("Waiting for a battle map...")
            return
        {"units": self.draw_units, "battle": self.draw_battle, "enemies": self.draw_enemies,
         "map": self.draw_map}[view](snap)

    # Units

    def draw_units(self, snap):
        blues = self.units(snap, "blue")
        if self.detail is not None:
            u = next((b for b in blues if b["slot"] == self.detail), None)
            if u:
                self.draw_unit_page(u, snap)
                return
            self.detail = None
        y = TAB_H + PAD
        self.header(snap, y)
        y += 26
        x, w = PAD, W - 2 * PAD
        lh = H - PAD - y
        self.frame(x, y, w, lh)
        danger = self.dangers(snap)
        page, sel = self.page_of(blues, "unit_sel", LIST_ROWS)
        for k, u in enumerate(blues[page * LIST_ROWS:(page + 1) * LIST_ROWS]):
            ry = y + 4 + k * 16
            i = page * LIST_ROWS + k
            if i == sel and self.ui.get("stick"):
                self.rect(x + 4, ry, w - 8, 16, WIN_DIM)
                self.arrow(x + 6, ry + 5, "r", INK)
            c = MUTED if u["acted"] else INK
            self.text(self.fit(u["name"], 60), x + 13, ry, c, None)
            self.text(self.fit(u["klass"]["name"], 62), x + 76, ry, MUTED, None)
            self.text("%d" % u["level"], x + 152, ry, c, None, "right")
            self.bar(x + 158, ry + 6, 30, u["hp"] / max(1, u["max_hp"]), self.hp_color(u["hp"], u["max_hp"]))
            self.text("%d/%d" % (u["hp"], u["max_hp"]), x + 192, ry, c, None)
            n, dmg = danger.get(u["slot"], (0, 0))
            if n and dmg >= u["hp"]:
                self.tag_right("can die", x + w - 6, ry, (233, 185, 178), (122, 31, 24))
            elif n:
                self.tag_right("%d reach" % n, x + w - 6, ry, (239, 214, 164), (106, 69, 8))
        pages = max(1, (len(blues) + LIST_ROWS - 1) // LIST_ROWS)
        if page:
            self.arrow(x + w - 12, y + 3, "u", INK)
        if page < pages - 1:
            self.arrow(x + w - 12, y + lh - 8, "d", INK)
        self._list = (y + 4, page, [u["slot"] for u in blues])

    def page_of(self, items, key, rows):
        sel = min(self.ui.get(key, 0), max(0, len(items) - 1))
        return sel // rows, sel

    def draw_unit_page(self, u, snap):
        rom = self.rom
        x, w = PAD, W - 2 * PAD
        y = TAB_H + PAD
        self.frame(x, y, w, 22, line=None)
        self.text(u["name"], x + 8, y + 3)
        self.text("%s · Lv %d · Exp %d" % (u["klass"]["name"], u["level"], u["exp"]), x + w - 8, y + 3,
                  MUTED, None, "right")
        y += 26
        # Stats: value, bar to the class cap, growth.
        sw = 150
        self.frame(x, y, sw, 8 * 16 + 8)
        self.text("now", x + 54, y + 3, MUTED, None, "right")
        self.text("grow", x + sw - 8, y + 3, MUTED, None, "right")
        growths = u["char"]["growths"]
        caps = u["klass"]["caps"]
        for i, name in enumerate(fe.STATS):
            ry = y + 4 + (i + 1) * 16
            v = u["max_hp"] if i == 0 else u["stats"][i]
            self.text(name, x + 8, ry, MUTED, None)
            self.text(str(v), x + 54, ry, align="right")
            cap = caps[i] if i < len(caps) else 30
            at_cap = cap and v >= cap
            self.bar(x + 60, ry + 6, 40, v / cap if cap else 0, BEST if at_cap else INK)
            g = growths[i] if i < len(growths) else 0
            gc = BEST if g >= 50 else RED if g <= 20 else INK
            self.text("%d%%" % g, x + sw - 8, ry, gc, None, "right")
        # Items and weapon ranks.
        ix = x + sw + 4
        iw = w - sw - 4
        self.frame(ix, y, iw, 8 * 16 + 8)
        eq, _ = fe.equipped(rom, u)
        ry = y + 4
        for iid, uses in u["items"]:
            it = rom.item(iid)
            if not it:
                continue
            c = INK if (not it["weapon"] or fe.can_wield(u, it)) else MUTED
            if eq and it is eq:
                self.arrow(ix + 5, ry + 5, "r", INK)
            self.text(self.fit(it["name"], iw - 44), ix + 12, ry, c, None)
            low = it["uses"] and uses <= max(3, it["uses"] // 10)
            self.text(str(uses), ix + iw - 8, ry, RED if low else c, None, "right")
            ry += 16
        ry = max(ry, y + 4 + 5 * 16) + 2
        ranks = [(fe.WEAPON_TYPES[t], wexp) for t, wexp in enumerate(u["ranks"]) if wexp]
        for name, wexp in ranks[:2]:
            nxt = fe.next_rank(wexp)
            label = "%s %s" % (name, fe.rank_letter(wexp))
            self.text(label, ix + 8, ry, MUTED, None)
            if nxt:
                self.text("%d to %s" % (nxt[1], nxt[0]), ix + iw - 8, ry, MUTED, None, "right")
            ry += 16
        y += 8 * 16 + 12
        self.frame(x, y, w, H - PAD - y)
        mine_n, dmg = self.dangers(snap).get(u["slot"], (0, 0))
        line = "Con %d · Mov %d · HP %d/%d" % (u["con"], u["mov"], u["hp"], u["max_hp"])
        self.text(line, x + 8, y + 3, MUTED, None)
        if mine_n:
            msg = "%d %s can reach, up to %d damage" % (mine_n, "enemy" if mine_n == 1 else "enemies", dmg)
            self.text(self.fit(msg, w - 16), x + 8, y + 19, RED if dmg >= u["hp"] else AMBER, None)
        else:
            self.text("No enemy can reach this unit now", x + 8, y + 19, BEST, None)

    # Battle

    def draw_battle(self, snap):
        b = snap.get("battle")
        if not b:
            self.message("Pick a target to attack: the odds show here")
            return
        a, d = b
        live_a = next((u for u in snap["units"] if u["char"]["ptr"] == a["char"] and u["faction"] == "blue"), None)
        live_d = next((u for u in snap["units"] if u["char"]["ptr"] == d["char"]), None)
        done = (live_a and live_a["hp"] != a["hp"]) or (live_d and live_d["hp"] != d["hp"]) or not live_d
        x, w = PAD, W - 2 * PAD
        y = TAB_H + PAD
        cw = (w - 4) // 2
        dmg_a, dmg_d = max(0, a["atk"] - d["def"]), max(0, d["atk"] - a["def"])
        wa, wd = self.rom.item(a["weapon"]), self.rom.item(d["weapon"])
        n_a = (2 if wa and wa["attr"] & fe.IA_BRAVE else 1)
        n_d = (2 if wd and wd["attr"] & fe.IA_BRAVE else 1)
        dbl_a, dbl_d = a["spd"] - d["spd"] >= 4, d["spd"] - a["spd"] >= 4
        counter = d["can_counter"] and wd is not None
        for k, (s, other, dmg, n, dbl, wpn, col) in enumerate((
                (a, d, dmg_a, n_a, dbl_a, wa, BLUE_UNIT), (d, a, dmg_d, n_d, dbl_d, wd, RED_UNIT))):
            cx = x + k * (cw + 4)
            self.frame(cx, y, cw, 84)
            self.text(self.fit(s["name"], cw - 16), cx + 8, y + 3, col, None)
            self.text(self.fit(wpn["name"] if wpn else "No weapon", cw - 16), cx + 8, y + 19, MUTED, None)
            self.text("HP", cx + 8, y + 35, MUTED, None)
            self.text("%d/%d" % (s["hp"], s["max_hp"]), cx + 30, y + 35)
            if k == 1 and not counter:
                self.text("Can't counter", cx + 8, y + 51, MUTED, None)
            else:
                times = n * (2 if dbl else 1)
                self.text("Dmg", cx + 8, y + 51, MUTED, None)
                self.text("%d" % dmg + (" ×%d" % times if times > 1 else ""), cx + 40, y + 51,
                          BEST if times > 1 else INK, None)
                self.text("Crit %d" % s["crit"], cx + cw - 8, y + 51, MUTED, None, "right")
                self.text("Hit", cx + 8, y + 67, MUTED, None)
                real = fe.true_hit(s["hit"])
                self.text("%d" % s["hit"], cx + 40, y + 67)
                self.text("real %s" % pct(real), cx + cw - 8, y + 67,
                          BEST if real * 100 > s["hit"] + 0.5 else RED if real * 100 < s["hit"] - 0.5 else INK,
                          None, "right")
        # The round: attacker, counter, follow-ups.
        pa, pd = fe.true_hit(a["hit"]), fe.true_hit(d["hit"])
        ca, cd = a["crit"] / 100.0, d["crit"] / 100.0
        seq = [("a", pa, ca, dmg_a)] * n_a
        if counter:
            seq += [("b", pd, cd, dmg_d)] * n_d
        if dbl_a:
            seq += [("a", pa, ca, dmg_a)] * n_a
        elif dbl_d and counter:
            seq += [("b", pd, cd, dmg_d)] * n_d
        odds = fe.fight_odds(seq, a["hp"], d["hp"])
        y += 88
        self.frame(x, y, w, H - PAD - y)
        ty = y + 3
        if done:
            self.text("Last battle (already fought)", x + 8, ty, MUTED, None)
            ty += 16
        kx = x + 8
        kx += self.tag("Kills: %s" % pct(odds["b_dies"]), kx, ty,
                       (184, 220, 192) if odds["b_dies"] > 0.5 else (239, 214, 164),
                       (31, 91, 49) if odds["b_dies"] > 0.5 else (106, 69, 8)) + 6
        if odds["a_dies"] > 0:
            self.tag("%s dies: %s" % (a["name"], pct(odds["a_dies"])), kx, ty, (233, 185, 178), (122, 31, 24))
        elif counter:
            self.tag("Hurt: %s" % pct(odds["a_hurt"]), kx, ty, (239, 214, 164), (106, 69, 8))
        ty += 18
        # What comes after: enemies that reach the tile you attack from.
        threats = snap.get("threats") or {}
        reds = {u["slot"]: u for u in self.units(snap, "red")}
        pos = (a["x"], a["y"])
        reach = [reds[s] for s, t in threats.items() if s in reds and pos in t
                 and not (live_d and reds[s] is live_d and odds["b_dies"] > 0.99)]
        if live_a and not done:
            mine, _ = fe.equipped(self.rom, live_a)
            terrain = snap["map"]["terrain"]
            tid = terrain[pos[1]][pos[0]] if pos[1] < len(terrain) and pos[0] < len(terrain[0]) else 1
            total = 0
            for e in reach:
                best = 0
                for it in fe.weapons(self.rom, e):
                    best = max(best, fe.damage(self.rom, e, it, live_a, tid, mine)
                               * fe.strikes(self.rom, e, it, live_a, mine))
                total += best
            left = a["hp"]
            if not reach:
                self.text("Enemy phase: no enemy reaches this tile", x + 8, ty, BEST, None)
            else:
                c = RED if total >= left else AMBER
                self.text(self.fit("Enemy phase: %d can reach this tile," % len(reach), w - 16), x + 8, ty, c, None)
                self.text("up to %d damage (before this fight's)" % total, x + 8, ty + 16, c, None)
                ty += 16
                if total >= left:
                    self.text("%s could die on the enemy phase" % a["name"], x + 8, ty + 16, RED, None)

    # Enemies

    def draw_enemies(self, snap):
        reds = sorted(self.units(snap, "red"), key=lambda u: (not u["boss"], u["y"], u["x"]))
        blues = self.units(snap, "blue")
        x, w = PAD, W - 2 * PAD
        y = TAB_H + PAD
        lh = ENEMY_ROWS * 16 + 8
        self.frame(x, y, w, lh)
        if not reds:
            self.text("No enemies in sight", W // 2, y + lh // 2 - 8, MUTED, None, "center")
        page, sel = self.page_of(reds, "enemy_sel", ENEMY_ROWS)
        for k, u in enumerate(reds[page * ENEMY_ROWS:(page + 1) * ENEMY_ROWS]):
            i = page * ENEMY_ROWS + k
            ry = y + 4 + k * 16
            if i == sel:
                self.rect(x + 4, ry, w - 8, 16, WIN_DIM)
                self.arrow(x + 6, ry + 5, "r", INK)
            self.text(self.fit(u["name"], 64), x + 13, ry, BLUE_UNIT if u["boss"] else INK, None)
            self.text("%d" % u["level"], x + 92, ry, MUTED, None, "right")
            it, _ = fe.equipped(self.rom, u)
            self.text(self.fit(it["name"] if it else "-", 70), x + 98, ry, MUTED, None)
            self.text("%d" % u["hp"], x + 186, ry, align="right")
            right = x + w - 6
            for label, bg, fg in self.enemy_tags(u, blues)[:2]:
                right -= self.tag_right(label, right, ry, bg, fg) + 3
        pages = max(1, (len(reds) + ENEMY_ROWS - 1) // ENEMY_ROWS)
        if page:
            self.arrow(x + w - 12, y + 3, "u", INK)
        if page < pages - 1:
            self.arrow(x + w - 12, y + lh - 8, "d", INK)
        self._list = (y + 4, page, [u["slot"] for u in reds])
        # The chosen enemy.
        y += lh + 4
        self.frame(x, y, w, H - PAD - y)
        if not reds:
            return
        u = reds[sel]
        s = u["stats"]
        self.text("%s · %s" % (u["name"], u["klass"]["name"]), x + 8, y + 3, BLUE_UNIT if u["boss"] else INK, None)
        self.text("HP %d/%d  Str %d  Skl %d  Spd %d  Def %d  Res %d  Mov %d" % (
            u["hp"], u["max_hp"], s[1], s[2], s[3], s[4], s[5], u["mov"]), x + 8, y + 19, MUTED, None)
        names = []
        for iid, uses in u["items"]:
            it = self.rom.item(iid)
            if it:
                names.append(it["name"])
        line = ", ".join(names)
        if u["drops"] and names:
            line += " (drops %s)" % names[-1]
        self.text(self.fit(line, w - 16), x + 8, y + 35)
        eff = [b["name"] for b in blues for it in fe.weapons(self.rom, u) if b["klass"]["id"] in it["effective"]]
        if eff:
            self.text(self.fit("Effective against " + ", ".join(dict.fromkeys(eff)), w - 16), x + 8, y + 51,
                      RED, None)

    def enemy_tags(self, u, blues):
        tags = []
        ws = fe.weapons(self.rom, u)
        if u["boss"]:
            tags.append(("boss", (188, 203, 224), (37, 62, 99)))
        eff = [b for b in blues for it in ws if b["klass"]["id"] in it["effective"]]
        if eff:
            tags.append(("×3 " + eff[0]["name"], (233, 185, 178), (122, 31, 24)))
        crit = max((it["crit"] for it in ws), default=0)
        if crit >= 10:
            tags.append(("crit %d" % crit, (233, 185, 178), (122, 31, 24)))
        if u["drops"]:
            tags.append(("drops", (184, 220, 192), (31, 91, 49)))
        far = max((it["max"] for it in ws), default=0)
        if far >= 2 and len(tags) < 2:
            tags.append(("range %d" % far, (201, 205, 210), (58, 63, 72)))
        return tags

    # Map

    def draw_map(self, snap):
        mp = snap["map"]
        w, h, terrain = mp["w"], mp["h"], mp["terrain"]
        info_h = 38
        avail_w, avail_h = W - 2 * PAD - 4, H - TAB_H - 2 * PAD - info_h - 8
        t = max(4, min(16, avail_w // w, avail_h // h))
        mw, mh = t * w, t * h
        ox, oy = (W - mw) // 2, TAB_H + PAD + 2 + (avail_h - mh) // 2
        self.rect(ox - 2, oy - 2, mw + 4, mh + 4, INK)
        for yy in range(h):
            row = terrain[yy]
            for xx in range(w):
                self.rect(ox + xx * t, oy + yy * t, t, t, TERRAIN_COLORS.get(row[xx], (206, 210, 196)))
        threats = snap.get("threats") or {}
        chosen = self.ui.get("map_enemy")
        if chosen is not None and chosen not in threats:
            chosen = self.ui["map_enemy"] = None
        danger = set().union(*threats.values()) if threats else set()
        for (xx, yy) in danger:
            self.rect(ox + xx * t, oy + yy * t, t, t, (210, 80, 70), 90)
        if chosen is not None:
            for (xx, yy) in threats[chosen]:
                self.rect(ox + xx * t, oy + yy * t, t, t, (232, 176, 64), 150)
        for u in snap["units"]:
            if u["rescued"]:
                continue
            c = {"blue": BLUE_UNIT, "red": RED_UNIT, "green": GREEN_UNIT}[u["faction"]]
            if u["acted"]:
                c = tuple((v + 2 * m) // 3 for v, m in zip(c, MUTED))
            px, py = ox + u["x"] * t, oy + u["y"] * t
            self.rect(px + 1, py + 1, t - 2, t - 2, c)
            if u["boss"]:
                self.outline(px, py, t, t, YELLOW)
            if u["faction"] == "red" and u["slot"] == chosen:
                self.outline(px, py, t, t, INK, 2)
        self._map_geom = (ox, oy, t, w, h)
        y = H - PAD - info_h
        self.frame(PAD, y, W - 2 * PAD, info_h)
        tile = self.ui.get("map_tile")
        if chosen is not None:
            e = next((u for u in self.units(snap, "red") if u["slot"] == chosen), None)
            if e:
                it, _ = fe.equipped(self.rom, e)
                self.text("%s · Lv %d · %s" % (e["name"], e["level"], it["name"] if it else "no weapon"),
                          PAD + 8, y + 3)
                self.text("Mov %d · range %s · gold: where it can hit" % (
                    e["mov"], "-".join(str(v) for v in sorted({it["min"] or 1, it["max"] or 1})) if it else "-"),
                    PAD + 8, y + 19, MUTED, None)
        elif tile and tile[0] < w and tile[1] < h:
            tid = terrain[tile[1]][tile[0]]
            self.text(self.rom.terrain_name(tid) or "?", PAD + 8, y + 3)
            blue = next((u for u in self.units(snap, "blue")), None)
            if blue:
                k = blue["klass"]
                self.text("Def +%d  Avoid +%d (for %s)" % (k["terrain_def"][tid], k["terrain_avoid"][tid],
                                                           k["name"]), PAD + 8, y + 19, MUTED, None)
        else:
            self.text("Red: tiles enemies can attack", PAD + 8, y + 3, INK, None)
            self.text("Tap an enemy for its own range", PAD + 8, y + 19, MUTED, None)

    def draw_settings(self, snap):
        x, w = PAD, W - 2 * PAD
        y = TAB_H + PAD
        self.frame(x, y, w, 90)
        rows = [("Game", self.rom.title if self.rom else "-"),
                ("Code", self.rom.code if self.rom else "-"),
                ("Chapter", str(snap.get("chapter", "-"))),
                ("RetroArch", "connected" if snap.get("connected") else "not answering")]
        for i, (k, v) in enumerate(rows):
            self.text(k, x + 8, y + 4 + i * 20, MUTED, None)
            self.text(v, x + 100, y + 4 + i * 20)

    # ---------- input ----------

    def stick_view(self, view, action, snap):
        step = 1 if action == "down" else -1 if action == "up" else 0
        if view == "units":
            blues = self.units(snap, "blue")
            if self.detail is not None:
                if action == "press":
                    self.detail = None
                return
            if not blues:
                return
            sel = min(self.ui.get("unit_sel", 0), len(blues) - 1)
            if action == "press" and self.ui.get("stick"):
                self.detail = blues[sel]["slot"]
            elif self.ui.get("stick"):
                self.ui["unit_sel"] = (sel + step) % len(blues)
            self.ui["stick"] = True
        elif view == "enemies":
            n = len(self.units(snap, "red"))
            if n:
                self.ui["enemy_sel"] = (min(self.ui.get("enemy_sel", 0), n - 1) + step) % n
        elif view == "map":
            reds = sorted(u["slot"] for u in self.units(snap, "red"))
            if action == "press" or not reds:
                self.ui["map_enemy"] = None
                return
            cur = self.ui.get("map_enemy")
            k = (reds.index(cur) + step) % len(reds) if cur in reds else (0 if step > 0 else len(reds) - 1)
            self.ui["map_enemy"] = reds[k]
            self.ui["map_tile"] = None

    def tap_view(self, view, x, y):
        snap = self.mem.snapshot() if self.mem else {}
        if view == "units":
            if self.detail is not None:
                self.detail = None
                return
            top, page, slots = getattr(self, "_list", (0, 0, []))
            k = (y - top) // 16
            i = page * LIST_ROWS + k
            if x >= W - PAD - 22 and len(slots) > LIST_ROWS and 0 <= k < LIST_ROWS:  # page arrows
                pages = (len(slots) + LIST_ROWS - 1) // LIST_ROWS
                self.ui["unit_sel"] = ((page + (1 if k >= LIST_ROWS // 2 else -1)) % pages) * LIST_ROWS
            elif 0 <= k < LIST_ROWS and i < len(slots):
                self.ui["unit_sel"] = i
                self.detail = slots[i]
        elif view == "enemies":
            top, page, slots = getattr(self, "_list", (0, 0, []))
            k = (y - top) // 16
            i = page * ENEMY_ROWS + k
            if x >= W - PAD - 22 and len(slots) > ENEMY_ROWS and 0 <= k < ENEMY_ROWS:  # page arrows
                pages = (len(slots) + ENEMY_ROWS - 1) // ENEMY_ROWS
                page = (page + (1 if k >= ENEMY_ROWS // 2 else -1)) % pages
                self.ui["enemy_sel"] = page * ENEMY_ROWS
            elif 0 <= k < ENEMY_ROWS and i < len(slots):
                self.ui["enemy_sel"] = i
        elif view == "map":
            geom = getattr(self, "_map_geom", None)
            if not geom:
                return
            ox, oy, t, w, h = geom
            tx, ty = (x - ox) // t, (y - oy) // t
            if not (0 <= tx < w and 0 <= ty < h):
                self.ui["map_enemy"] = self.ui["map_tile"] = None
                return
            hit = next((u for u in self.units(snap, "red") if (u["x"], u["y"]) == (tx, ty)), None)
            if hit:
                self.ui["map_enemy"] = None if self.ui.get("map_enemy") == hit["slot"] else hit["slot"]
                self.ui["map_tile"] = None
            else:
                self.ui["map_enemy"] = None
                self.ui["map_tile"] = (tx, ty)
