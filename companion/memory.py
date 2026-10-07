# SPDX-License-Identifier: GPL-2.0-or-later
"""Game RAM: where the party, battle, bag and location live, and reading them.

Known engines start from the pret decomp addresses (FireRed rev 0 is kept by
CFRU hacks such as Unbound and Odyssey, Emerald by many Emerald hacks). Every
address is checked against what it holds; anything that fails is searched for
in RAM by its shape and remembered per ROM, so unknown hacks mostly work too.
"""

import json
import os
import struct
import threading
import time

import gen3
from ra import RAError, RAReadError

EWRAM, EWRAM_SIZE = 0x02000000, 0x40000
IWRAM, IWRAM_SIZE = 0x03000000, 0x8000
STATE_DIR = "/storage/.config/mgbaqol/games"
BATTLE_MON = 0x58
RESCAN_SECONDS = 15

ENGINES = {
    "fr": {"battle_mons": 0x02023BE4, "gmain": 0x030030F0,
           "map_header": 0x02036DFC, "bag_pockets": 0x0203988C,
           "pockets": ["Items", "Key Items", "Poké Balls", "TMs & HMs", "Berries"]},
    "em": {"battle_mons": 0x02024084, "gmain": 0x030022C0,
           "map_header": 0x02037318, "bag_pockets": 0x02039DD8,
           "pockets": ["Items", "Poké Balls", "TMs & HMs", "Berries", "Key Items"]},
}
SIX_POCKETS = ["Items", "Medicine", "Poké Balls", "TMs & HMs", "Berries", "Key Items"]


def u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def is_rom_ptr(p):
    return 0x08000000 <= p < 0x0A000000


def is_ewram_ptr(p):
    return EWRAM <= p < EWRAM + EWRAM_SIZE


def decode_battle_mon(raw):
    species = u16(raw, 0)
    level, hp, max_hp = raw[0x2A], u16(raw, 0x28), u16(raw, 0x2C)
    if not 0 < species < 2048 or not 1 <= level <= 100 or not 0 < max_hp or hp > max_hp:
        return None
    return {
        "species": species,
        "stats": dict(zip(("Atk", "Def", "Spe", "SpA", "SpD"), struct.unpack_from("<5H", raw, 2))),
        "moves": list(struct.unpack_from("<4H", raw, 0x0C)),
        "stages": [s - 6 for s in struct.unpack_from("<8b", raw, 0x18)],
        "types": [raw[0x21], raw[0x22]],
        "pp": list(raw[0x24:0x28]),
        "hp": hp, "level": level, "max_hp": max_hp,
        "item": u16(raw, 0x2E),
        "nick": gen3.decode_text(raw[0x30:0x3B]),
        "status": u32(raw, 0x4C),
        "pid": u32(raw, 0x48),
    }


def party_runs(mem, base):
    """Start addresses of runs of valid party Pokemon in a memory dump."""
    out = []
    for off in range(0, len(mem) - gen3.MON_SIZE, 4):
        if not gen3.plausible(gen3.decode_mon(mem[off:off + gen3.MON_SIZE])):
            continue
        if off >= gen3.MON_SIZE and gen3.plausible(gen3.decode_mon(mem[off - gen3.MON_SIZE:off])):
            continue  # inside a run that starts earlier
        n = 1
        while n < 6 and gen3.plausible(gen3.decode_mon(mem[off + n * gen3.MON_SIZE:off + (n + 1) * gen3.MON_SIZE])):
            n += 1
        tail = mem[off + n * gen3.MON_SIZE:off + n * gen3.MON_SIZE + 8]
        if n < 6 and tail != bytes(8):
            continue  # a real party is followed by an empty slot; PC box data is not
        out.append(base + off)
    return out


def decode_party_at(raw):
    """Party from 600 bytes: consecutive valid slots until the first empty one."""
    party = []
    for slot in range(6):
        m = gen3.decode_mon(raw[slot * gen3.MON_SIZE:(slot + 1) * gen3.MON_SIZE])
        if m is None:
            break
        if not gen3.plausible(m):
            return None  # torn read or not a party
        party.append(m)
    return party


class Store:
    """Per-ROM choices and discovered addresses, kept across runs."""

    def __init__(self, crc):
        self.path = os.path.join(STATE_DIR, crc + ".json")
        try:
            with open(self.path) as f:
                self.data = json.load(f)
        except (OSError, ValueError):
            self.data = {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
        try:
            os.makedirs(STATE_DIR, exist_ok=True)
            with open(self.path, "w") as f:
                json.dump(self.data, f, indent=1)
        except OSError:
            pass

    def reset(self):
        keep = {k: v for k, v in self.data.items() if k == "party_mode"}
        self.data = {}
        for k, v in keep.items():
            self.set(k, v)
        self.set("reset_at", int(time.time()))


class GameMemory(threading.Thread):
    """Polls RetroArch about once a second and publishes a snapshot for the UI."""

    def __init__(self, ra, rom, profile, on_change):
        super().__init__(daemon=True)
        self.ra, self.rom, self.on_change = ra, rom, on_change
        self.engine = ENGINES.get(rom.engine, ENGINES["fr"])
        self.store = Store(rom.crc)
        self.profile_party = profile[1] if profile else None
        self.view = "party"           # which tab the UI shows; bag/map are read only when visible
        self.lock = threading.Lock()
        self.snap = {"connected": False, "party": [], "in_battle": False, "battle": None,
                     "bag": None, "location": None, "candidates": [], "found": {}}
        self.last_scan = {}
        self.party_prev = {}
        self.requests = set()
        self.stop = threading.Event()

    # ---------- UI side ----------

    def snapshot(self):
        with self.lock:
            return dict(self.snap)

    def request(self, what):
        """'rescan_party' or 'reset' from the settings screen."""
        with self.lock:
            self.requests.add(what)

    def set_party_mode(self, mode):
        self.store.set("party_mode", mode)
        self.party_prev = {}

    # ---------- helpers ----------

    def read(self, addr, n):
        return self.ra.read(addr, n)

    def _publish(self, **kw):
        with self.lock:
            changed = any(self.snap.get(k) != v for k, v in kw.items())
            self.snap.update(kw)
        if changed:
            self.on_change()

    def _may_scan(self, kind):
        now = time.monotonic()
        if now - self.last_scan.get(kind, -1e9) < RESCAN_SECONDS:
            return False
        self.last_scan[kind] = now
        return True

    def _addr(self, key):
        """Discovered address, else the engine default."""
        found = self.store.get("found", {})
        return found.get(key, self.engine.get(key))

    def _remember(self, key, addr):
        found = dict(self.store.get("found", {}))
        if found.get(key) != addr:
            found[key] = addr
            self.store.set("found", found)

    def _forget(self, key):
        found = dict(self.store.get("found", {}))
        if key in found:
            del found[key]
            self.store.set("found", found)

    # ---------- party ----------

    def _party_candidates(self):
        cands = self.store.get("party_candidates")
        if cands is None and self._may_scan("party"):
            ew = self.read(EWRAM, EWRAM_SIZE)
            iw = self.read(IWRAM, IWRAM_SIZE)
            cands = party_runs(ew, EWRAM) + party_runs(iw, IWRAM)
            if cands:
                self.store.set("party_candidates", cands)
        cands = list(cands or [])
        if self.profile_party and self.profile_party not in cands:
            cands.insert(0, self.profile_party)
        return cands

    def _read_party(self):
        mode = self.store.get("party_mode", "auto")
        cands = self._party_candidates()
        if mode != "auto":
            addr = int(mode, 16)
        elif self.store.get("party_learned") in cands:
            addr = self.store.get("party_learned")
        elif self.profile_party:
            addr = self.profile_party
        elif cands:
            addr = cands[0]
        else:
            return None, cands, None
        parties = {}
        for c in cands if mode == "auto" and len(cands) > 1 else [addr]:
            parties[c] = decode_party_at(self.read(c, gen3.MON_SIZE * 6))
        self.all_parties = [p for p in parties.values() if p]
        self._learn_live_party(parties)
        if mode == "auto":
            learned = self.store.get("party_learned")
            if learned in parties and (parties[learned] or not self.all_parties):
                addr = learned
            elif not parties.get(addr) and self.all_parties:
                # The chosen copy is empty but another isn't (say a menu buffer
                # was cleared): show a non-empty one rather than nothing.
                addr = next(a for a, p in parties.items() if p)
        return parties.get(addr), cands, addr

    def _learn_live_party(self, parties):
        """The live party changes while you play; the save-block copy only when you save.

        When exactly one candidate goes from one real party to a different real
        party between polls, that one is live. Copies that empty out (menu
        buffers being cleared) don't count.
        """
        changed = [a for a, p in parties.items()
                   if p and self.party_prev.get(a) and self.party_prev[a] != p]
        if len(changed) == 1 and self.store.get("party_learned") != changed[0]:
            self.store.set("party_learned", changed[0])
        self.party_prev.update({a: p for a, p in parties.items() if p is not None})

    # ---------- battle ----------

    def _gmain_ok(self, addr):
        a = self.read(addr, 0x28)
        time.sleep(0.1)
        b = self.read(addr, 0x28)
        return is_rom_ptr(u32(a, 4)) and 1 <= u32(b, 0x20) - u32(a, 0x20) <= 30

    def _find_gmain(self):
        a = self.read(IWRAM, IWRAM_SIZE)
        time.sleep(0.3)
        b = self.read(IWRAM, IWRAM_SIZE)
        for o in range(0, IWRAM_SIZE - 0x440, 4):
            if (is_rom_ptr(u32(a, o + 4)) and (u32(a, o) == 0 or is_rom_ptr(u32(a, o)))
                    and 3 <= u32(b, o + 0x20) - u32(a, o + 0x20) <= 60
                    and 0 <= u32(b, o + 0x24) - u32(a, o + 0x24) <= 60):
                return IWRAM + o
        return None

    def _in_battle(self):
        gmain = self._addr("gmain")
        if not self.store.get("found", {}).get("gmain"):
            if gmain and self._gmain_ok(gmain):
                self._remember("gmain", gmain)
            elif self._may_scan("gmain"):
                gmain = self._find_gmain()
                if gmain is None:
                    return None
                self._remember("gmain", gmain)
            else:
                return None
        return bool(self.read(gmain + 0x439, 1)[0] & 2)

    def _battle_matches_party(self, mons, party):
        """Your battler must be one of your Pokemon, in any copy of the party found in RAM."""
        if not mons or not mons[0]:
            return False
        pool = list(party or []) + [m for p in getattr(self, "all_parties", []) for m in p]
        return any(m["species"] == mons[0]["species"] and m["level"] == mons[0]["level"]
                   and m["max_hp"] == mons[0]["max_hp"] for m in pool)

    def _read_battle(self, party):
        addr = self._addr("battle_mons")
        mons = [decode_battle_mon(r) for r in self._chunks(self.read(addr, BATTLE_MON * 4))]
        if self._battle_matches_party(mons, party):
            self._remember("battle_mons", addr)
            return mons
        if party and self._may_scan("battle"):
            ew = self.read(EWRAM, EWRAM_SIZE)
            for o in range(0, EWRAM_SIZE - BATTLE_MON * 4, 4):
                m = decode_battle_mon(ew[o:o + BATTLE_MON])
                if m and self._battle_matches_party([m], party) and decode_battle_mon(
                        ew[o + BATTLE_MON:o + 2 * BATTLE_MON]):
                    self._remember("battle_mons", EWRAM + o)
                    return [decode_battle_mon(r) for r in self._chunks(ew[o:o + BATTLE_MON * 4])]
        return None

    @staticmethod
    def _chunks(raw):
        return [raw[i * BATTLE_MON:(i + 1) * BATTLE_MON] for i in range(len(raw) // BATTLE_MON)]

    # ---------- save blocks, bag, location ----------

    @staticmethod
    def _pockets_ok(raw, n, strict=False):
        """n {ItemSlot *ptr, capacity, padding} entries over separate memory ranges.

        Vanilla pockets tile one range in SaveBlock1; hacks with a bigger bag
        (Odyssey) scatter them, so only `strict` (used when searching all of
        RAM) demands the tiling.
        """
        entries = []
        for i in range(n):
            # capacity is a u8 in pret's struct BagPocket; CFRU bags (Odyssey's
            # 400-slot Items pocket) widen it to u16. Either way the rest is padding.
            ptr, cap = u32(raw, i * 8), u16(raw, i * 8 + 4)
            if not is_ewram_ptr(ptr) or not 1 <= cap <= 1000 or raw[i * 8 + 6:i * 8 + 8] != bytes(2):
                return None
            entries.append((ptr, cap))
        spans = sorted(entries)
        for (a, ca), (b, _) in zip(spans, spans[1:]):
            if a + ca * 4 > b or (strict and a + ca * 4 != b):
                return None
        return entries

    def _find_pockets(self):
        addr = self._addr("bag_pockets")
        for n in (5, 6):
            if self._pockets_ok(self.read(addr, n * 8), n):
                return addr, n
        if not self._may_scan("bag"):
            return None
        ew = self.read(EWRAM, EWRAM_SIZE)
        for n in (6, 5):
            for o in range(0, EWRAM_SIZE - n * 8, 4):
                if self._pockets_ok(ew[o:o + n * 8], n, strict=True):
                    return EWRAM + o, n
        return None

    @staticmethod
    def _bag_key(pockets):
        """Quantities are XOR'd with the save's encryption key (low 16 bits).

        Rather than finding SaveBlock2 (its pointer moves between hacks), solve
        for the key: key items and TMs always hold quantity 1, so raw ^ 1 is a
        candidate; pick the one that makes every quantity sane (1..999).
        """
        cands = {0}
        for name, items in pockets:
            if name in ("Key Items", "TMs & HMs"):
                cands.update(q ^ 1 for _, q in items)
        best, best_sum = 0, None
        for k in cands:
            qs = [q ^ k for _, items in pockets for _, q in items]
            if all(1 <= q <= 999 for q in qs) and (best_sum is None or sum(qs) < best_sum):
                best, best_sum = k, sum(qs)
        return best

    def _read_bag(self):
        found = self._find_pockets()
        if not found:
            return None
        addr, n = found
        self._remember("bag_pockets", addr)
        entries = self._pockets_ok(self.read(addr, n * 8), n)
        if not entries:
            return None
        slots = [self.read(ptr, cap * 4) for ptr, cap in entries]
        names = SIX_POCKETS if n == 6 else self.engine["pockets"]
        pockets = []
        for name, raw in zip(names, slots):
            items = [struct.unpack_from("<HH", raw, i * 4) for i in range(len(raw) // 4)]
            pockets.append((name, [(item, qty) for item, qty in items if item]))
        key = self._bag_key(pockets)
        return [(name, [(item, qty ^ key) for item, qty in items]) for name, items in pockets]

    def _read_location(self):
        raw = self._read_map_header()
        if raw is None:
            return None
        ids = self.rom.map_id(raw)
        return {"mapsec": raw[0x14], "group": ids[0] if ids else None, "num": ids[1] if ids else None}

    def _read_map_header(self):
        addr = self._addr("map_header")
        raw = self.read(addr, 0x1C)
        trusted = self.store.get("found", {}).get("map_header") == addr
        if (trusted and is_rom_ptr(u32(raw, 0))) or self._is_map_header(raw):
            self._remember("map_header", addr)
            return raw
        if not self._may_scan("map"):
            return None
        ew = self.read(EWRAM, EWRAM_SIZE)
        for o in range(0, EWRAM_SIZE - 0x1C, 4):
            if self._is_map_header(ew[o:o + 0x1C]):
                self._remember("map_header", EWRAM + o)
                return ew[o:o + 0x1C]
        return None

    def _is_map_header(self, raw):
        """gMapHeader is a byte-for-byte copy of the current map's header in ROM."""
        if not all(is_rom_ptr(u32(raw, k)) for k in (0, 4, 8)):
            return False
        return self.rom.rom.find(raw[:0x18]) >= 0

    # ---------- main loop ----------

    def _handle_requests(self):
        with self.lock:
            reqs, self.requests = self.requests, set()
        if "rescan_party" in reqs:
            self.store.set("party_candidates", None)
            self.store.set("party_learned", None)
            self.last_scan.pop("party", None)
            self.party_prev = {}
        if "reset" in reqs:
            self.store.reset()
            self.last_scan.clear()
            self.party_prev = {}

    @staticmethod
    def _guard(fn, *args):
        """A wrong address guess only blanks that view; a lost connection still propagates."""
        try:
            return fn(*args)
        except RAReadError as e:
            print("[mgbaqol] %s: %s" % (fn.__name__, e), flush=True)
            return None

    def poll(self):
        self._handle_requests()
        party, cands, party_addr = self._read_party()
        out = {"connected": True, "candidates": cands, "party_addr": party_addr}
        if party is not None:
            out["party"] = party
        party = party if party is not None else self.snap["party"]

        in_battle = self._guard(self._in_battle)
        out["in_battle"] = bool(in_battle)
        out["battle"] = self._guard(self._read_battle, party) if in_battle else None
        if self.view == "bag":
            out["bag"] = self._guard(self._read_bag)
        if self.view == "map":
            out["location"] = self._guard(self._read_location)
        if self.view == "settings":
            previews = {}
            for c in cands:
                p = decode_party_at(self.read(c, gen3.MON_SIZE * 6))
                previews[c] = [m["species"] for m in p] if p else None
            out["previews"] = previews
            out["party_mode"] = self.store.get("party_mode", "auto")
            out["learned"] = self.store.get("party_learned")
        out["found"] = dict(self.store.get("found", {}))
        self._publish(**out)

    def run(self):
        while not self.stop.is_set():
            try:
                self.poll()
            except RAError:
                self._publish(connected=False)
            except Exception as e:  # keep the companion alive on odd data
                print("[mgbaqol] poll error: %r" % e, flush=True)
            self.stop.wait(0.5 if self.snap.get("in_battle") else 1.0)
