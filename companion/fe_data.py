# SPDX-License-Identifier: GPL-2.0-or-later
"""Fire Emblem 7 (GBA, USA): game data from the ROM and the live game from RAM.

ROM tables are found through the pointers the game's own code loads them from
(the same places FEBuilder patches), so hacks that move or expand them still
work. RAM addresses are FE7U's; the unit structs are checked as they are read.
"""

import struct
import threading
import time

from ra import RAError

# Where the game's code keeps the addresses of its tables (FE7U).
PTR_TEXT, PTR_HUFF_TREE, PTR_HUFF_ROOT = 0x12CB8, 0x6BC, 0x6B8
PTR_ITEMS, PTR_CLASSES, PTR_CHARS, PTR_TERRAIN_NAMES = 0x16060, 0x178F0, 0x17890, 0x19B1C

ITEM_SIZE, CLASS_SIZE, CHAR_SIZE = 0x24, 0x54, 0x34

# RAM (FE7U).
PLAY_STATE = 0x0202BBF8          # chapter state: +0xD vision, +0xE chapter, +0xF phase, +0x10 turn
UNIT_SIZE = 0x48
FACTIONS = {"blue": (0x0202BD50, 62), "red": (0x0202CEC0, 50), "green": (0x0202DCD0, 20)}
MAP_INFO = 0x0202E3D8             # u16 w, h, then row-pointer arrays: unit, terrain, movement, range, fog
BATTLE_ACTOR, BATTLE_TARGET, BATTLE_SIZE = 0x0203A3F0, 0x0203A470, 0x80

STATS = ("HP", "Str", "Skl", "Spd", "Def", "Res", "Lck")
WEAPON_TYPES = ("Sword", "Lance", "Axe", "Bow", "Staff", "Anima", "Light", "Dark")
RANKS = ((251, "S"), (181, "A"), (121, "B"), (71, "C"), (31, "D"), (1, "E"))
MAGIC_TYPES = (5, 6, 7)

# Unit state bits.
US_HIDDEN, US_ACTED, US_DEAD, US_NOT_DEPLOYED, US_RESCUED, US_DROP = 0x1, 0x2, 0x4, 0x8, 0x20, 0x1000
# Item attribute bits.
IA_WEAPON, IA_MAGIC, IA_STAFF, IA_BRAVE, IA_MAGIC_DAMAGE, IA_REVERSE = 0x1, 0x2, 0x4, 0x20, 0x40, 0x100
CA_BOSS = 0x8000

# Weapon triangle: (attacker type, defender type) -> +1 / -1.
TRIANGLE = {(0, 2): 1, (2, 1): 1, (1, 0): 1, (2, 0): -1, (1, 2): -1, (0, 1): -1,
            (5, 6): 1, (6, 7): 1, (7, 5): 1, (6, 5): -1, (7, 6): -1, (5, 7): -1}


def rank_letter(wexp):
    for need, letter in RANKS:
        if wexp >= need:
            return letter
    return "-"


def next_rank(wexp):
    """(letter, points needed) of the next rank, or None at S."""
    for need, letter in reversed(RANKS):
        if wexp < need:
            return letter, need - wexp
    return None


def _true_hit_table():
    """FE7 rolls two numbers 0-99 and hits if their average is below the shown rate."""
    pairs = [0] * 199                      # how many (a, b) sum to each value
    for a in range(100):
        for b in range(100):
            pairs[a + b] += 1
    table, below = [], 0                   # below = pairs with a + b < 2h
    for h in range(101):
        table.append(below / 10000.0)
        below += sum(pairs[2 * h:2 * h + 2])
    return table


TRUE_HIT = _true_hit_table()


def true_hit(shown):
    """Real chance (0-1) of a hit the game shows as `shown` percent."""
    return TRUE_HIT[max(0, min(100, shown))]


class FERom:
    def __init__(self, path):
        with open(path, "rb") as f:
            self.rom = f.read()
        self.title = self.rom[0xA0:0xAC].decode("ascii", "replace").strip("\0 ")
        self.code = self.rom[0xAC:0xB0].decode("ascii", "replace")
        self.text_table = self.ptr(PTR_TEXT)
        self.tree = self.ptr(PTR_HUFF_TREE)
        self.root = self.ptr(self.ptr(PTR_HUFF_ROOT))
        self.items = self.ptr(PTR_ITEMS)
        self.classes = self.ptr(PTR_CLASSES)
        self.chars = self.ptr(PTR_CHARS)
        self.terrain_names = self.ptr(PTR_TERRAIN_NAMES)
        self._text = {}
        self._class_cache = {}
        self._char_cache = {}
        self._item_cache = {}

    def u8(self, o):
        return self.rom[o]

    def u16(self, o):
        return struct.unpack_from("<H", self.rom, o)[0]

    def u32(self, o):
        return struct.unpack_from("<I", self.rom, o)[0]

    def ptr(self, o):
        """ROM offset a pointer stored at o points to."""
        return self.u32(o) & 0x01FFFFFF

    # ---------- text ----------

    def text(self, tid):
        if tid in self._text:
            return self._text[tid]
        s = ""
        try:
            p = self.u32(self.text_table + tid * 4)
            if p & 0x80000000:          # anti-Huffman patch: plain text at the address
                s = self._plain(p & 0x01FFFFFF)
            elif 0x08000000 <= p < 0x0A000000:
                s = self._huffman(p & 0x01FFFFFF)
        except (struct.error, IndexError):
            s = ""
        self._text[tid] = s
        return s

    def _plain(self, o):
        end = self.rom.find(b"\0", o, o + 400)
        return self._clean(self.rom[o:end if end >= 0 else o + 400])

    def _huffman(self, o, limit=600):
        out = bytearray()
        rom, root, tree = self.rom, self.root, self.tree
        node, bit = root, 0
        while bit < limit * 8:
            b = (rom[o + (bit >> 3)] >> (bit & 7)) & 1
            bit += 1
            node = tree + struct.unpack_from("<H", rom, node + 2 * b)[0] * 4
            if struct.unpack_from("<H", rom, node + 2)[0] == 0xFFFF:
                v = struct.unpack_from("<H", rom, node)[0]
                if v & 0xFF == 0:
                    break
                out.append(v & 0xFF)
                if v >> 8:
                    out.append(v >> 8)
                node = root
        return self._clean(bytes(out))

    @staticmethod
    def _clean(raw):
        """Drops control codes (portraits, pauses); line breaks become spaces."""
        out, i = [], 0
        while i < len(raw):
            c = raw[i]
            if c in (1, 2):
                out.append(" ")
            elif c == 0x10:              # [LoadFace] + 2 argument bytes
                i += 2
            elif c >= 0x20:
                out.append(chr(c))
            i += 1
        return " ".join("".join(out).split())

    # ---------- records ----------

    def item(self, iid):
        """Item record as a dict, or None for 0 / out of range."""
        if not iid:
            return None
        hit = self._item_cache.get(iid)
        if hit is not None:
            return hit
        o = self.items + iid * ITEM_SIZE
        if o + ITEM_SIZE > len(self.rom):
            return None
        r = self.rom
        rng = r[o + 0x19]
        eff = self.ptr(o + 0x10) if self.u32(o + 0x10) else 0
        it = {
            "id": iid, "name": self.text(self.u16(o)), "desc": self.text(self.u16(o + 2)),
            "type": r[o + 7], "attr": self.u32(o + 8), "uses": r[o + 0x14], "mt": r[o + 0x15],
            "hit": r[o + 0x16], "wt": r[o + 0x17], "crit": r[o + 0x18],
            "min": rng >> 4, "max": rng & 0xF, "rank": r[o + 0x1C],
            "effective": self._class_list(eff) if eff else (),
        }
        it["weapon"] = bool(it["attr"] & IA_WEAPON) and it["type"] < 8 and it["type"] != 4
        it["magic"] = it["type"] in MAGIC_TYPES or bool(it["attr"] & IA_MAGIC_DAMAGE)
        self._item_cache[iid] = it
        return it

    def _class_list(self, o):
        out = []
        while o < len(self.rom) and self.rom[o] and len(out) < 40:
            out.append(self.rom[o])
            o += 1
        return tuple(out)

    def klass(self, ptr):
        """Class record from the pointer a unit holds."""
        hit = self._class_cache.get(ptr)
        if hit is not None:
            return hit
        o = ptr & 0x01FFFFFF
        r = self.rom
        k = {
            "ptr": ptr, "id": r[o + 4], "name": self.text(self.u16(o)),
            "con": r[o + 0x11], "mov": r[o + 0x12],
            "caps": list(r[o + 0x13:o + 0x19]) + [30],     # HP..Res, Luck caps at 30
            "move_cost": r[self.ptr(o + 0x38):self.ptr(o + 0x38) + 0x41],
            "terrain_avoid": r[self.ptr(o + 0x44):self.ptr(o + 0x44) + 0x41],
            "terrain_def": r[self.ptr(o + 0x48):self.ptr(o + 0x48) + 0x41],
            "ability": self.u32(o + 0x28),
        }
        self._class_cache[ptr] = k
        return k

    def char(self, ptr):
        hit = self._char_cache.get(ptr)
        if hit is not None:
            return hit
        o = ptr & 0x01FFFFFF
        r = self.rom
        c = {
            "ptr": ptr, "id": r[o + 4], "name": self.text(self.u16(o)), "desc": self.text(self.u16(o + 2)),
            # Personal bases are signed: they adjust the class's (Batta's Con is -2).
            "con": struct.unpack_from("<b", r, o + 0x13)[0], "growths": list(r[o + 0x1C:o + 0x23]),
            "ability": self.u32(o + 0x28),
        }
        self._char_cache[ptr] = c
        return c

    def terrain_name(self, tid):
        try:
            return self.text(self.u16(self.terrain_names + tid * 2))
        except struct.error:
            return "?"


class Unit(dict):
    """A unit from RAM with its char / class records attached."""


def decode_unit(rom, raw, faction, slot, addr):
    cptr, kptr = struct.unpack_from("<II", raw)
    if not (0x08000000 <= cptr < 0x0A000000 and 0x08000000 <= kptr < 0x0A000000):
        return None
    state = struct.unpack_from("<I", raw, 0x0C)[0]
    if state & (US_DEAD | US_NOT_DEPLOYED):
        return None
    char, klass = rom.char(cptr), rom.klass(kptr)
    u = Unit(
        faction=faction, slot=slot, addr=addr, char=char, klass=klass,
        name=char["name"] or klass["name"], level=raw[8], exp=raw[9], state=state,
        x=raw[0x10], y=raw[0x11], max_hp=raw[0x12], hp=raw[0x13],
        stats=[raw[0x12]] + list(raw[0x14:0x1A]),          # HP Str Skl Spd Def Res Lck
        con=klass["con"] + char["con"] + raw[0x1A], mov=klass["mov"] + raw[0x1D],
        items=[(raw[0x1E + 2 * k], raw[0x1F + 2 * k]) for k in range(5) if raw[0x1E + 2 * k]],
        ranks=list(raw[0x28:0x30]),
    )
    u["boss"] = bool(char["ability"] & CA_BOSS)
    u["acted"] = bool(state & US_ACTED)
    u["hidden"] = bool(state & US_HIDDEN)
    u["rescued"] = bool(state & US_RESCUED)
    u["drops"] = bool(state & US_DROP)
    return u


def equipped(rom, u):
    """The first weapon in the inventory the unit can wield: (item dict, uses) or (None, 0)."""
    for iid, uses in u["items"]:
        it = rom.item(iid)
        if it and it["weapon"] and can_wield(u, it):
            return it, uses
    return None, 0


def can_wield(u, it):
    if not it or not it["weapon"]:
        return False
    if it["type"] >= len(u["ranks"]):
        return False
    rank = u["ranks"][it["type"]]
    return rank > 0 and rank >= it["rank"]


def weapons(rom, u):
    return [rom.item(iid) for iid, _ in u["items"] if can_wield(u, rom.item(iid))]


def attack_speed(u, it):
    return u["stats"][3] - max(0, (it["wt"] if it else 0) - u["con"])


def damage(rom, att, it, dfn, dfn_terrain, dfn_weapon=None):
    """Damage per hit of att with item it against dfn on terrain id dfn_terrain (no crit)."""
    if not it:
        return 0
    mt = it["mt"] * (3 if dfn["klass"]["id"] in it["effective"] else 1)
    tri = TRIANGLE.get((it["type"], dfn_weapon["type"]), 0) if dfn_weapon else 0
    if it["attr"] & IA_REVERSE or (dfn_weapon and dfn_weapon["attr"] & IA_REVERSE):
        tri = -tri
    power = att["stats"][1] + mt + tri     # FE7 has one Str/Mag stat
    defense = dfn["stats"][5] if it["magic"] else dfn["stats"][4]
    k = dfn["klass"]
    if 0 <= dfn_terrain < len(k["terrain_def"]):
        defense += k["terrain_def"][dfn_terrain]
    return max(0, power - defense)


def strikes(rom, att, it, dfn, dfn_weapon):
    """How many times att hits per round: doubling and brave weapons."""
    n = 2 if it and it["attr"] & IA_BRAVE else 1
    if attack_speed(att, it) - attack_speed(dfn, dfn_weapon) >= 4:
        n *= 2
    return n


# ---------- the map: who can reach where ----------

def reachable(terrain, w, h, start, mov, costs, blocked):
    """Tiles a unit can end its move on: {(x, y): cost}. blocked: tiles it can't pass through."""
    import heapq
    best = {start: 0}
    heap = [(0, start)]
    while heap:
        c, (x, y) = heapq.heappop(heap)
        if c > best.get((x, y), 99):
            continue
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if not (0 <= nx < w and 0 <= ny < h) or (nx, ny) in blocked:
                continue
            t = terrain[ny][nx]
            step = costs[t] if t < len(costs) else 0xFF
            if step == 0xFF or step == 0:
                continue
            nc = c + step
            if nc <= mov and nc < best.get((nx, ny), 99):
                best[(nx, ny)] = nc
                heapq.heappush(heap, (nc, (nx, ny)))
    return best


def threat(rom, u, terrain, w, h, occupied_by):
    """Tiles unit u can attack this coming phase: {(x, y)}; empty without a weapon.

    occupied_by: {(x, y): faction}. Units pass their own side's units (and
    red/green pass each other), never the other side's.
    """
    ws = weapons(rom, u)
    if not ws:
        return set()
    friendly = ("red",) if u["faction"] == "red" else ("blue", "green")
    blocked = {p for p, f in occupied_by.items() if f not in friendly}
    reach = reachable(terrain, w, h, (u["x"], u["y"]), u["mov"], u["klass"]["move_cost"], blocked)
    stands = [p for p in reach if p == (u["x"], u["y"]) or p not in occupied_by]
    lo = min(it["min"] or 1 for it in ws)
    hi = max(it["max"] or 1 for it in ws)
    out = set()
    for sx, sy in stands:
        for dx in range(-hi, hi + 1):
            rest = hi - abs(dx)
            for dy in range(-rest, rest + 1):
                d = abs(dx) + abs(dy)
                if lo <= d <= hi:
                    tx, ty = sx + dx, sy + dy
                    if 0 <= tx < w and 0 <= ty < h:
                        out.add((tx, ty))
    return out


# ---------- battle odds ----------

def fight_odds(seq, hp_a, hp_b):
    """Probabilities after a round of strikes.

    seq: list of (side, p_hit, p_crit_given_hit, dmg) with side 'a' or 'b'
    striking the other. Returns {"a_dies": p, "b_dies": p, "a_hurt": p}.
    """
    states = {(hp_a, hp_b): 1.0}
    for side, ph, pc, dmg in seq:
        nxt = {}
        for (a, b), p in states.items():
            if a <= 0 or b <= 0:
                nxt[(a, b)] = nxt.get((a, b), 0) + p
                continue
            outcomes = ((ph * (1 - pc), dmg), (ph * pc, dmg * 3), (1 - ph, 0))
            for q, d in outcomes:
                if q <= 0:
                    continue
                na, nb = (a - d, b) if side == "b" else (a, b - d)
                key = (max(0, na), max(0, nb))
                nxt[key] = nxt.get(key, 0) + p * q
        states = nxt
    return {
        "a_dies": sum(p for (a, b), p in states.items() if a <= 0),
        "b_dies": sum(p for (a, b), p in states.items() if b <= 0),
        "a_hurt": sum(p for (a, b), p in states.items() if a < hp_a),
    }


class FEMemory(threading.Thread):
    """Polls the running game twice a second; snapshot() gives a consistent view."""

    def __init__(self, ra, rom, on_change):
        super().__init__(daemon=True)
        self.ra, self.rom, self.on_change = ra, rom, on_change
        self.view = "units"
        self.lock = threading.Lock()
        self.snap = {"connected": False}
        self._terrain_key = None
        self._terrain = None
        self._threat_key = None
        self._threats = {}

    def snapshot(self):
        with self.lock:
            return dict(self.snap)

    def run(self):
        last = None
        while True:
            try:
                snap = self.poll()
            except RAError:
                snap = {"connected": False}
            except Exception as e:  # keep the companion alive whatever the game does
                print("[mgbaqol] fe poll: %r" % e, flush=True)
                snap = {"connected": True, "error": repr(e)}
            key = repr(snap.get("units")) + repr(snap.get("battle")) + repr(snap.get("turn")) + \
                str(snap.get("connected"))
            with self.lock:
                self.snap = snap
            if key != last:
                last = key
                self.on_change()
            time.sleep(0.5)

    def poll(self):
        ra, rom = self.ra, self.rom
        ps = ra.read(PLAY_STATE, 0x18)
        snap = {"connected": True, "chapter": ps[0xE], "phase": ps[0xF],
                "turn": struct.unpack_from("<H", ps, 0x10)[0], "vision": ps[0xD]}
        units = []
        for faction, (base, count) in FACTIONS.items():
            raw = ra.read(base, UNIT_SIZE * count)
            for i in range(count):
                u = decode_unit(rom, raw[i * UNIT_SIZE:(i + 1) * UNIT_SIZE], faction, i, base + i * UNIT_SIZE)
                if u:
                    units.append(u)
        snap["units"] = units
        mi = ra.read(MAP_INFO, 0x20)
        w, h = struct.unpack_from("<HH", mi)
        if not (1 <= w <= 64 and 1 <= h <= 64) or not units:
            snap["map"] = None
            return snap
        rows = struct.unpack_from("<5I", mi, 4)   # unit, terrain, movement, range, fog
        tkey = (w, h, rows[1], snap["chapter"])
        if tkey != self._terrain_key:
            self._terrain = self._layer(rows[1], w, h)
            self._terrain_key = tkey
        terrain = self._terrain
        fog = self._layer(rows[4], w, h) if snap["vision"] else None
        snap["map"] = {"w": w, "h": h, "terrain": terrain, "fog": fog}
        # Under fog, the enemies you can't see stay unseen here too.
        if fog:
            units = [u for u in units if u["faction"] != "red" or fog[u["y"]][u["x"]]]
            snap["units"] = units
        snap["threats"] = self._threats_for(units, terrain, w, h)
        snap["battle"] = self._battle()
        return snap

    def _layer(self, rows_ptr, w, h):
        ptrs = struct.unpack_from("<%dI" % h, self.ra.read(rows_ptr, 4 * h))
        stride = ptrs[1] - ptrs[0] if h > 1 else w
        data = self.ra.read(ptrs[0], stride * (h - 1) + w)
        return [data[y * stride:y * stride + w] for y in range(h)]

    def _threats_for(self, units, terrain, w, h):
        key = tuple((u["faction"], u["slot"], u["x"], u["y"], u["hp"], tuple(u["items"])) for u in units)
        if key == self._threat_key:
            return self._threats
        occupied = {(u["x"], u["y"]): u["faction"] for u in units if not u["rescued"]}
        out = {}
        for u in units:
            if u["faction"] == "red" and not u["rescued"]:
                out[u["slot"]] = threat(self.rom, u, terrain, w, h, occupied)
        self._threat_key, self._threats = key, out
        return out

    def _battle(self):
        raw = self.ra.read(BATTLE_ACTOR, BATTLE_SIZE * 2)
        sides = []
        for k in range(2):
            b = raw[k * BATTLE_SIZE:(k + 1) * BATTLE_SIZE]
            cptr, kptr = struct.unpack_from("<II", b)
            if not (0x08000000 <= cptr < 0x0A000000 and 0x08000000 <= kptr < 0x0A000000):
                return None
            # attack, defense, speed, hit, avoid, hit vs this foe, crit, dodge, crit vs this foe
            s = struct.unpack_from("<9H", b, 0x5A)
            sides.append({
                "char": cptr, "x": b[0x10], "y": b[0x11], "max_hp": b[0x12], "hp": b[0x72],
                # The unit's index says its side: 1-63 yours, 0x40+ other, 0x80+ enemy.
                "faction": "red" if b[0xB] & 0x80 else "green" if b[0xB] & 0x40 else "blue",
                "weapon": b[0x48], "weapon_type": b[0x50], "can_counter": b[0x52],
                "tri_hit": struct.unpack_from("<b", b, 0x53)[0], "tri_atk": struct.unpack_from("<b", b, 0x54)[0],
                "terrain": b[0x55], "atk": s[0], "def": s[1], "spd": s[2], "hit": s[5], "crit": s[8],
                "name": self.rom.char(cptr)["name"],
            })
        return sides
