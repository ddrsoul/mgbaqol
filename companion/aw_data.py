# SPDX-License-Identifier: GPL-2.0-or-later
"""Advance Wars 2: Black Hole Rising (USA): game data from the ROM and the live battle from RAM.

The ROM tables (units with their damage charts, terrain, movement costs, COs
with their firepower / defense / movement modifiers) were found by content in
AW2E; RAM addresses come from watching the game change.
"""

import struct
import threading
import time

from ra import RAError

# ROM (AW2E).
STRINGS = 0x610A38            # table of pointers to strings
UNITS, UNIT_SIZE = 0x5D5B18, 92  # record for unit type t at UNITS + (t - 1) * UNIT_SIZE
TERRAIN, TERRAIN_SIZE = 0x5D5848, 20
MOVE_CLEAR, MOVE_SNOW, MOVE_RAIN = 0x5D511C, 0x5D51FC, 0x5D52DC   # + move type * 32, by terrain type
COS, CO_SIZE, CO_COUNT = 0x5D3DD0, 0x104, 19
CO_MODES = (0x50, 0x94, 0xD8)  # day to day, CO Power, Super CO Power: 3 move tables then 8 modifiers
ARMY_NAMES = ("", "Orange Star", "Blue Moon", "Green Earth", "Yellow Comet", "Black Hole")

# RAM.
MAP_SIZE = 0x0201E450         # u16 width, height
MAP_TERRAIN = 0x0201F882      # one byte per tile, row by row: type in the low 5 bits, owner above
UNIT_SLOTS = 0x02022690       # army a's 64 units at UNIT_SLOTS + a * 0x300, 12 bytes each
UNIT_REC, SLOTS = 12, 64
ARMIES = 0x020232C0           # army a at ARMIES + a * 0x3C
ARMY_SIZE = 0x3C
CO_FIELD = 0x1D               # index into the CO table (0 Nell, 1 Andy, 2 Max, 3 Olaf...)
POWER_FIELD = 0x1E            # 0 none, 1 CO Power, 2 Super CO Power
METER_FIELD = 0x20            # u32: funds value of damage dealt (half) and taken (full)
USES_FIELD = 0x25             # powers used so far
STAR, STAR_STEP = 9000, 1800  # meter per star; every power used adds 1800 (20%) to it
DAY, CURRENT_ARMY = 0x03004080, 0x03004088
FOG = 0x03003FCD              # fog of war rule: 1 on
CURSOR = 0x03003140           # x, y

CATEGORY = ("foot", "vehicle", "plane", "copter", "ship")
TRANSPORTS = {7, 20, 23}      # APC, T Copter, Lander (unit type ids)
DAILY_FUEL = {16: 5, 17: 5, 19: 2, 20: 2, 21: 1, 22: 1, 23: 1, 24: 1}   # planes, copters, ships burn fuel daily


class AWRom:
    def __init__(self, path):
        with open(path, "rb") as f:
            self.rom = f.read()
        self.title = self.rom[0xA0:0xAC].decode("ascii", "replace").strip("\0 ")
        self.code = self.rom[0xAC:0xB0].decode("ascii", "replace")
        self._units = {}
        self._cos = {}

    def u16(self, o):
        return struct.unpack_from("<H", self.rom, o)[0]

    def u32(self, o):
        return struct.unpack_from("<I", self.rom, o)[0]

    def string(self, idx):
        try:
            p = self.u32(STRINGS + 4 * idx) & 0x01FFFFFF
        except struct.error:
            return ""
        end = self.rom.find(b"\0", p, p + 200)
        return self.rom[p:end].decode("latin-1") if end > p else ""

    def unit(self, t):
        """Unit type record (t = the type byte in RAM, 1-based)."""
        if t in self._units:
            return self._units[t]
        o = UNITS + (t - 1) * UNIT_SIZE
        r = self.rom
        u = {
            "type": t, "name": self.string(self.u16(o)), "cost": self.u16(o + 6) * 10,
            "move": r[o + 0xA], "ammo": r[o + 0xB], "vision": r[o + 0xC],
            "min": r[o + 0xE], "max": r[o + 0xF], "fuel": r[o + 0x10],
            "category": r[o + 0x18], "move_type": r[o + 0x19],
            "primary": list(r[o + 0x1F:o + 0x1F + 24]), "secondary": list(r[o + 0x39:o + 0x39 + 24]),
            "weapon1": self.string(self.u16(o + 2)), "weapon2": self.string(self.u16(o + 4)),
        }
        u["armed"] = any(u["primary"]) or any(u["secondary"])
        u["indirect"] = u["min"] > 1
        self._units[t] = u
        return u

    def terrain(self, t):
        t &= 0x1F
        o = TERRAIN + t * TERRAIN_SIZE
        return {"type": t, "name": self.string(self.u16(o)), "stars": self.rom[o + 4]}

    def move_cost(self, move_type, terrain, weather=0):
        base = (MOVE_CLEAR, MOVE_RAIN, MOVE_SNOW)[weather] if weather in (0, 1, 2) else MOVE_CLEAR
        return self.rom[base + move_type * 32 + (terrain & 0x1F)]

    def co(self, cid):
        """{name, cop_stars, scop_stars, modes: [[(fp, def, move, range)] * 8] * 3}."""
        if cid in self._cos:
            return self._cos[cid]
        if not 0 <= cid < CO_COUNT:
            return None
        o = COS + cid * CO_SIZE
        modes = []
        for m in CO_MODES:
            mods = []
            for k in range(8):
                p = self.u32(o + m + 12 + 4 * k) & 0x01FFFFFF
                mods.append(struct.unpack_from("<4h", self.rom, p) if 0 < p < len(self.rom) - 8 else (0, 0, 0, 0))
            modes.append(mods)
        c = {"id": cid, "name": self.string(self.u16(o)), "cop": self.u32(o + 0xC), "scop": self.u32(o + 0x10),
             "modes": modes}
        self._cos[cid] = c
        return c

    def modifier(self, co, mode, u):
        """Summed (firepower, defense, move, range) of a CO mode for unit type record u."""
        if not co:
            return (0, 0, 0, 0)
        mods = co["modes"][min(mode, 2)]
        picks = [mods[u["category"]] if u["category"] < 5 else (0, 0, 0, 0)]
        if u["armed"]:
            picks.append(mods[6] if u["indirect"] else mods[5])
        if u["type"] in TRANSPORTS:
            picks.append(mods[7])
        return tuple(sum(p[i] for p in picks) for i in range(4))


def display_hp(hp):
    return (hp + 9) // 10


def base_damage(att_u, att_ammo, def_u):
    """(base %, weapon) for att_u hitting def_u: the stronger of its weapons that can fire.

    The main weapon needs ammo. The charts list e.g. a tank's cannon against
    infantry too, but the game fires the machine gun there, the bigger number.
    """
    t = def_u["type"] - 1
    if not 0 <= t < 24:
        return 0, ""
    p = att_u["primary"][t] if (att_ammo > 0 or not att_u["ammo"]) else 0
    s = att_u["secondary"][t]
    if p >= s and p:
        return p, att_u["weapon1"]
    return (s, att_u["weapon2"]) if s else (0, "")


def damage_range(rom, att, dfn, terrain_byte, att_hp=None, def_hp=None):
    """(min %, max %) att deals to dfn standing on terrain_byte; None if it can't hit it."""
    au, du = att["unit"], dfn["unit"]
    base, _ = base_damage(au, att["ammo"], du)
    if not base:
        return None
    fp = rom.modifier(att["co"], att["power"], au)[0]
    df = rom.modifier(dfn["co"], dfn["power"], du)[1]
    ahp = display_hp(att["hp"] if att_hp is None else att_hp)
    dhp = display_hp(dfn["hp"] if def_hp is None else def_hp)
    stars = 0 if du["category"] in (2, 3) else rom.terrain(terrain_byte)["stars"]
    luck_hi = 9
    if att["co"] and att["co"]["name"] == "Nell":
        luck_hi = (19, 59, 99)[min(att["power"], 2)]
    out = []
    for luck in (0, luck_hi):
        v = (base * (100 + fp) / 100.0 + luck) * ahp / 10.0 * (200 - (100 + df + stars * dhp)) / 100.0
        out.append(max(0, int(v)))
    return tuple(out), luck_hi


def kill_chance(rom, att, dfn, terrain_byte):
    r = damage_range(rom, att, dfn, terrain_byte)
    if not r:
        return 0.0
    (lo, hi), luck_hi = r
    if lo >= dfn["hp"]:
        return 1.0
    if hi < dfn["hp"]:
        return 0.0
    au, du = att["unit"], dfn["unit"]
    base, _ = base_damage(au, att["ammo"], du)
    fp = rom.modifier(att["co"], att["power"], au)[0]
    df = rom.modifier(dfn["co"], dfn["power"], du)[1]
    ahp, dhp = display_hp(att["hp"]), display_hp(dfn["hp"])
    stars = 0 if du["category"] in (2, 3) else rom.terrain(terrain_byte)["stars"]
    kills = 0
    for luck in range(luck_hi + 1):
        v = (base * (100 + fp) / 100.0 + luck) * ahp / 10.0 * (200 - (100 + df + stars * dhp)) / 100.0
        kills += int(v) >= dfn["hp"]
    return kills / (luck_hi + 1)


HIDING = {4, 19}              # woods, reef: units there are seen only from next door
PROPERTY_TYPES = {6, 8, 10, 11, 14, 17, 18, 20}   # city, HQ, airport, port, base, silo, lab


def visible_tiles(units, terrain, w, h, army):
    """Tiles army can see under fog: its units' vision (+3 for foot soldiers on
    mountains), its own properties; woods and reefs only from an adjacent tile."""
    seen = set()
    near = set()
    for u in units:
        if u["army"] != army:
            continue
        ut = u["unit"]
        vis = ut["vision"] + (3 if ut["category"] == 0 and terrain[u["y"]][u["x"]] & 0x1F == 3 else 0)
        for dx in range(-vis, vis + 1):
            rest = vis - abs(dx)
            for dy in range(-rest, rest + 1):
                tx, ty = u["x"] + dx, u["y"] + dy
                if 0 <= tx < w and 0 <= ty < h:
                    seen.add((tx, ty))
                    if abs(dx) + abs(dy) <= 1:
                        near.add((tx, ty))
    for y in range(h):
        for x in range(w):
            tb = terrain[y][x]
            if tb & 0x1F in PROPERTY_TYPES and (tb >> 5) == army + 1:
                seen.add((x, y))
                near.add((x, y))
    return {p for p in seen if terrain[p[1]][p[0]] & 0x1F not in HIDING or p in near}


def reachable(rom, u, terrain, w, h, blocked, weather=0):
    """Tiles unit u can end its move on: {(x, y): cost}."""
    import heapq
    ut = u["unit"]
    mov = max(0, min(ut["move"] + u["mod"][2], u["fuel"]))
    start = (u["x"], u["y"])
    best = {start: 0}
    heap = [(0, start)]
    while heap:
        c, (x, y) = heapq.heappop(heap)
        if c > best.get((x, y), 99):
            continue
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if not (0 <= nx < w and 0 <= ny < h) or (nx, ny) in blocked:
                continue
            step = rom.move_cost(ut["move_type"], terrain[ny][nx], weather)
            if step == 0xFF or step == 0:
                continue
            nc = c + step
            if nc <= mov and nc < best.get((nx, ny), 99):
                best[(nx, ny)] = nc
                heapq.heappush(heap, (nc, (nx, ny)))
    return best


def strike_tiles(rom, u, terrain, w, h, units, weather=0):
    """Tiles u can fire at on its next move: from where it stands if indirect, after moving if direct."""
    ut = u["unit"]
    if not ut["armed"]:
        return set()
    lo = ut["min"]
    hi = max(lo, ut["max"] + u["mod"][3])
    if ut["indirect"]:
        stands = [(u["x"], u["y"])]
    else:
        enemy_tiles = {(o["x"], o["y"]) for o in units if o["army"] != u["army"]}
        own_tiles = {(o["x"], o["y"]) for o in units if o["army"] == u["army"] and o is not u}
        reach = reachable(rom, u, terrain, w, h, enemy_tiles, weather)
        stands = [p for p in reach if p not in own_tiles]
    out = set()
    for sx, sy in stands:
        for dx in range(-hi, hi + 1):
            rest = hi - abs(dx)
            for dy in range(-rest, rest + 1):
                if lo <= abs(dx) + abs(dy) <= hi:
                    tx, ty = sx + dx, sy + dy
                    if 0 <= tx < w and 0 <= ty < h:
                        out.add((tx, ty))
    return out


class AWMemory(threading.Thread):
    def __init__(self, ra, rom, on_change):
        super().__init__(daemon=True)
        self.ra, self.rom, self.on_change = ra, rom, on_change
        self.view = "army"
        self.lock = threading.Lock()
        self.snap = {"connected": False}
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
            except Exception as e:
                print("[mgbaqol] aw poll: %r" % e, flush=True)
                snap = {"connected": True, "error": repr(e)}
            key = repr((snap.get("units"), snap.get("cursor"), snap.get("day"), snap.get("current"),
                        snap.get("connected"), [a.get("funds") for a in snap.get("armies") or []]))
            with self.lock:
                self.snap = snap
            if key != last:
                last = key
                self.on_change()
            time.sleep(0.4)

    def poll(self):
        ra, rom = self.ra, self.rom
        w, h = struct.unpack("<HH", ra.read(MAP_SIZE, 4))
        snap = {"connected": True}
        if not (5 <= w <= 30 and 5 <= h <= 30):
            snap["map"] = None
            return snap
        raw = ra.read(MAP_TERRAIN, w * h)
        terrain = [raw[y * w:(y + 1) * w] for y in range(h)]
        armies_raw = ra.read(ARMIES, ARMY_SIZE * 4)
        slots = ra.read(UNIT_SLOTS, 0x300 * 4)
        armies, units = [], []
        for a in range(4):
            ar = armies_raw[a * ARMY_SIZE:(a + 1) * ARMY_SIZE]
            co = rom.co(ar[CO_FIELD])
            power = ar[POWER_FIELD] if ar[POWER_FIELD] <= 2 else 0
            mine = []
            for s in range(SLOTS):
                rec = slots[a * 0x300 + s * UNIT_REC:a * 0x300 + (s + 1) * UNIT_REC]
                t = rec[0]
                if not 1 <= t <= 24:
                    continue
                ut = rom.unit(t)
                if not ut["name"]:
                    continue
                hv = struct.unpack_from("<H", rec, 4)[0]
                x, y = rec[2], rec[3]
                if not (x < w and y < h):
                    continue
                u = {"army": a, "slot": s, "unit": ut, "x": x, "y": y, "hp": hv & 0x7F,
                     "ammo": (hv >> 7) & 0xF, "fuel": rec[6], "moved": bool(rec[1] & 1),
                     "co": co, "power": power}
                u["mod"] = rom.modifier(co, power, ut)
                mine.append(u)
            if mine or struct.unpack_from("<I", ar)[0]:
                armies.append({"index": a, "funds": struct.unpack_from("<I", ar)[0], "co": co, "power": power,
                               "meter": struct.unpack_from("<I", ar, METER_FIELD)[0],
                               "star": STAR + STAR_STEP * ar[USES_FIELD],
                               "units": len(mine),
                               "value": sum(u["unit"]["cost"] * display_hp(u["hp"]) // 10 for u in mine)})
            units += mine
        cur = ra.read(CURSOR, 2)
        st = ra.read(DAY, 0x10)
        snap["fog"] = ra.read(FOG, 1)[0] == 1
        if snap["fog"]:
            snap["visible"] = {a["index"]: visible_tiles(units, terrain, w, h, a["index"]) for a in armies}
        snap.update(map={"w": w, "h": h, "terrain": terrain}, units=units, armies=armies,
                    cursor=(cur[0], cur[1]), day=struct.unpack_from("<H", st, 0)[0],
                    current=st[8] - 1 if 1 <= st[8] <= 4 else None)
        snap["threats"] = self._threats_for(units, terrain, w, h)
        return snap

    def _threats_for(self, units, terrain, w, h):
        key = tuple((u["army"], u["slot"], u["x"], u["y"], u["hp"], u["ammo"], u["fuel"]) for u in units)
        if key == self._threat_key:
            return self._threats
        out = {(u["army"], u["slot"]): strike_tiles(self.rom, u, terrain, w, h, units) for u in units}
        self._threat_key, self._threats = key, out
        return out
