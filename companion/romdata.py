# SPDX-License-Identifier: GPL-2.0-or-later
"""Game data read straight from the ROM: names, types, moves, items, sprites.

Hacks repoint and resize these tables, so each one is located by content
(known neighbouring entries) instead of a fixed offset, and the offsets are
cached per ROM CRC.
"""

import json
import pickle
import os
import re
import struct
import zipfile
import zlib

from gen3 import decode_text, encode_text

CACHE_DIR = "/storage/.config/mgbaqol/cache"
CACHE_VERSION = 10  # bump when table discovery changes

# Canonical type names keyed by the ROM's (upper-cased) spelling.
TYPE_ALIASES = {"FIGHT": "Fighting", "ELECTR": "Electric", "PSYCHC": "Psychic", "???": "???"}


def load_rom(path):
    if path.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".gba"))
            return z.read(name)
    with open(path, "rb") as f:
        return f.read()


def lz77(rom, off):
    """GBA BIOS LZ77UnComp."""
    if rom[off] != 0x10:
        raise ValueError("not LZ77 at 0x%X" % off)
    size = rom[off + 1] | rom[off + 2] << 8 | rom[off + 3] << 16
    out = bytearray()
    i = off + 4
    while len(out) < size:
        flags = rom[i]
        i += 1
        for bit in range(8):
            if len(out) >= size:
                break
            if flags & (0x80 >> bit):
                b1, b2 = rom[i], rom[i + 1]
                i += 2
                length = (b1 >> 4) + 3
                disp = ((b1 & 0xF) << 8 | b2) + 1
                for _ in range(length):
                    out.append(out[-disp])
            else:
                out.append(rom[i])
                i += 1
    return bytes(out[:size])


def _name_score(rom, base, stride, count=1500):
    """How many of the first `count` records hold a real name (letters, no '?').

    Hacks often leave the vanilla table in the ROM next to their expanded one;
    the expanded one has far more real names past the vanilla end.
    """
    score = 0
    for i in range(1, count):
        off = base + i * stride
        if off < 0 or off + 2 > len(rom):
            break
        name = decode_text(rom[off:off + min(stride, 24)])
        if len(name) >= 2 and "?" not in name and any(c.isalpha() for c in name):
            score += 1
    return score


def find_records(rom, anchor_sets, max_stride=0x200):
    """Locates a table of name records by known names at known indexes.

    `anchor_sets` is a list of [(index, name), ...]. When several tables match
    (a hack's expanded table and the vanilla one it replaced), the one with the
    most real names wins. Returns (base, stride) where base is the record of index 0.
    """
    found = set()
    for anchors in anchor_sets:
        (i0, n0), rest = anchors[0], anchors[1:]
        first = encode_text(n0) + b"\xFF"
        others = [(i - i0, encode_text(n) + b"\xFF") for i, n in rest]
        pos = rom.find(first)
        while pos != -1:
            for stride in range(max(len(first), 4), max_stride):
                if all(rom.startswith(enc, pos + d * stride) for d, enc in others):
                    found.add((pos - i0 * stride, stride))
                    break
            pos = rom.find(first, pos + 1)
    if not found:
        return None
    return max(found, key=lambda bs: _name_score(rom, bs[0], bs[1]))


def _anchors(*names_by_index, first=1):
    """Anchor sets in upper and title case: _anchors("Pound", "Karate Chop")."""
    pairs = [(first + i, n) for i, n in enumerate(names_by_index) if n]
    return [[(i, n.upper()) for i, n in pairs], [(i, n) for i, n in pairs]]


def find_stats(rom, first, second, offset, max_stride=0x100):
    """Locates a fixed-stride struct table by two consecutive known byte patterns.

    `first` belongs to index 1 and starts `offset` bytes into its record.
    Returns (base of index 0, stride).
    """
    pos = rom.find(first)
    while pos != -1:
        for stride in range(len(first), max_stride):
            if rom.startswith(second, pos + stride):
                return pos - offset - stride, stride
        pos = rom.find(first, pos + 1)
    return None


def _points_to_lz(rom, entry, sizes):
    """True if the pointer at `entry` leads to LZ77 data of one of `sizes`."""
    p = struct.unpack_from("<I", rom, entry)[0] - 0x08000000
    if not 0 <= p < len(rom) - 4 or rom[p] != 0x10:
        return False
    return (rom[p + 1] | rom[p + 2] << 8 | rom[p + 3] << 16) in sizes


def _table_ok(rom, base, sizes):
    return base >= 0 and all(_points_to_lz(rom, base + i * 8, sizes) for i in range(1, 4))


def _table_len(rom, base, sizes, tag_off):
    """Consecutive entries from species 1 that point to LZ data and carry tag == index."""
    n = 1
    while base + (n + 1) * 8 <= len(rom):
        entry = base + n * 8
        if struct.unpack_from("<H", rom, entry + tag_off)[0] != n or not _points_to_lz(rom, entry, sizes):
            break
        n += 1
    return n - 1


def _species_tables(rom, bases, sizes, tag_off, min_len=250):
    """Tables long enough to be per-species (trainer pic tables are short)."""
    return [b for b in bases if _table_len(rom, b, sizes, tag_off) >= min_len]


def _opaque_pixels(rom, table, species):
    p = struct.unpack_from("<I", rom, table + species * 8)[0] - 0x08000000
    tiles = lz77(rom, p)[:0x800]
    return sum((b & 0xF != 0) + (b >> 4 != 0) for b in tiles)


def _pick_front_table(rom, tables):
    """Front and back sheets look alike; Gen 3 back sprites are drawn bigger, so
    the front table is the one with fewer opaque pixels."""
    if len(tables) < 2:
        return tables[0] if tables else None
    sample = range(1, 11)
    return min(tables[:2], key=lambda t: sum(_opaque_pixels(rom, t, s) for s in sample))


def find_sheet_tables(rom):
    """Finds CompressedSpriteSheet tables {ptr, size, tag=species} for species 1..3."""
    pat = re.compile(rb"(?s)(.{3}[\x08\x09])(..)\x01\x00.{3}[\x08\x09]\2\x02\x00.{3}[\x08\x09]\2\x03\x00")
    found = []
    for m in pat.finditer(rom):
        base = m.start() - 8
        if m.start() % 4 == 0 and _table_ok(rom, base, (0x800, 0x1000)):
            found.append(base)
    return found


def find_palette_tables(rom):
    """Finds CompressedSpritePalette tables {ptr, tag=species, pad} for species 1..3."""
    pat = re.compile(rb"(?s).{3}[\x08\x09]\x01\x00...{3}[\x08\x09]\x02\x00...{3}[\x08\x09]\x03\x00..")
    return [m.start() - 8 for m in pat.finditer(rom)
            if m.start() % 4 == 0 and _table_ok(rom, m.start() - 8, (0x20,))]


def _text_at_ptr(rom, entry, limit=200):
    p = struct.unpack_from("<I", rom, entry)[0] - 0x08000000
    if not 0 <= p < len(rom):
        return None
    return decode_text(rom[p:p + limit])


def _desc_run(rom, base):
    n = 0
    while base + (n + 2) * 4 <= len(rom) and _text_at_ptr(rom, base + (n + 1) * 4):
        n += 1
    return n


def find_move_descriptions(rom):
    """Finds the move description pointer table (indexed by move id).

    Wording differs between games ("Wags the tail to lower the foe's DEFENSE."
    vs "The user wags its tail cutely, making the foe lower its Defense stat."),
    so Tail Whip (move 39) is found by keywords and checked against Growl (45)
    and Ember (52).
    """
    bases = set()
    for keyword in ("Defense", "DEFENSE"):
        enc = encode_text(keyword)
        seen = set()
        pos = rom.find(enc)
        while pos != -1:
            start = pos
            while start > 0 and rom[start - 1] != 0xFF and pos - start < 200:
                start -= 1
            if start not in seen:
                seen.add(start)
                if "tail" in decode_text(rom[start:start + 200]).lower():
                    ptr = struct.pack("<I", 0x08000000 + start)
                    q = rom.find(ptr)
                    while q != -1:
                        base = q - 39 * 4
                        if q % 4 == 0 and base >= 0:
                            growl = (_text_at_ptr(rom, base + 45 * 4) or "").lower()
                            ember = (_text_at_ptr(rom, base + 52 * 4) or "").lower()
                            if "attack" in growl and "burn" in ember:
                                bases.add(base)
                        q = rom.find(ptr, q + 1)
            pos = rom.find(enc, pos + 1)
    # Unbound keeps the vanilla 354-entry table next to its expanded one.
    return max(bases, key=lambda b: _desc_run(rom, b)) if bases else None


def _short_text(rom, ptr, limit=24):
    """Decoded text if `ptr` points at a short terminated string, else None."""
    p = ptr - 0x08000000
    if not 0 <= p < len(rom) - limit:
        return None
    raw = rom[p:p + limit]
    end = raw.find(b"\xFF")
    if end < 2:
        return None
    return decode_text(raw[:end + 1])


def find_mapsec_names(rom, engine):
    """Finds the map-section name table by what its entries say.

    FireRed-engine games keep a plain pointer array starting at mapsec 0x58;
    Emerald-engine games keep {x, y, w, h, name} records starting at mapsec 0.
    Of all long enough pointer runs, the one whose names most often say
    Town/City/Route wins, so new regions (Unbound's Borrius) work as well.
    Returns (offset of the first record, stride, first mapsec) or None.
    """
    if engine == "em":
        pat, stride, first = re.compile(rb"(?s)(?:[\x00-\x3f]{4}.{3}[\x08\x09]){40,}"), 8, 0
    else:
        pat, stride, first = re.compile(rb"(?s)(?:.{3}[\x08\x09]){40,}"), 4, 0x58
        # FireRed's sMapNames stays at its vanilla spot in CFRU hacks (Unbound,
        # Odyssey) even when every name is new, so try that first.
        vanilla = 0x3F1CAC
        if vanilla + 109 * 4 <= len(rom) and sum(
                _short_text(rom, struct.unpack_from("<I", rom, vanilla + i * 4)[0]) is not None
                for i in range(109)) >= 100:
            return vanilla, 4, first
    words = ("town", "city", "route", "cave", "forest", "island", "road", "mt.", "tower")
    best, best_score = None, 0.0
    for m in pat.finditer(rom):
        if m.start() % 4:
            continue
        n = (m.end() - m.start()) // stride
        names = [_short_text(rom, struct.unpack_from("<I", rom, m.start() + i * stride + stride - 4)[0])
                 for i in range(n)]
        good = [s for s in names if s]
        if len(good) < n * 0.8:
            continue
        score = sum(any(w in s.lower() for w in words) for s in good) / n
        if score > best_score:
            best, best_score = m.start(), score
    return (best, stride, first) if best is not None and best_score > 0.25 else None


def find_wild_headers(rom):
    """Finds gWildMonHeaders: {group, num, pad[2], land, water, rocks, fishing[, extra]}.

    Vanilla records are 20 bytes; some hacks (Emerald Enhanced) append a fifth
    pointer. Returns (offset, stride) or None.
    """
    for nptr in (4, 5):
        stride = 4 + nptr * 4
        rec = rb"[\x00-\x3f][\x00-\x7f]\x00\x00(?:\x00\x00\x00\x00|.{3}[\x08\x09]){%d}" % nptr
        pat = re.compile(rb"(?s)(?:" + rec + rb"){16,}")
        for m in pat.finditer(rom):
            if m.start() % 4:
                continue
            base = m.start()
            # The land table of the first record with one must hold 12 sane slots.
            for i in range((m.end() - base) // stride):
                land = struct.unpack_from("<I", rom, base + i * stride + 4)[0]
                if land:
                    info = land - 0x08000000
                    mons = struct.unpack_from("<I", rom, info + 4)[0] - 0x08000000
                    if 0 < rom[info] <= 100 and 0 <= mons < len(rom) - 48 and all(
                            rom[mons + k * 4] <= rom[mons + k * 4 + 1] <= 100 for k in range(12)):
                        # The match can start mid-table; walk back to its first record.
                        one = re.compile(rb"(?s)" + rec)
                        while base >= stride and one.fullmatch(rom, base - stride, base):
                            base -= stride
                        return base, stride
                    break
    return None


# Encounter slot odds (%) per method, fixed by the Gen 3 engine.
WILD_ODDS = {
    "Grass": [20, 20, 10, 10, 10, 10, 5, 5, 4, 4, 1, 1],
    "Surfing": [60, 30, 5, 4, 1],
    "Rock Smash": [60, 30, 5, 4, 1],
    "Fishing": [70, 30, 60, 20, 20, 40, 40, 15, 4, 1],
}
FISHING_RODS = ["Old Rod"] * 2 + ["Good Rod"] * 3 + ["Super Rod"] * 5


# FireRed 1.0 region_map.c literal-pool words. CFRU and most binary hacks keep
# this code in place and only repoint its data, so these words say where each
# hack keeps its own map (PokeDaisy's notes on the FireRed ROM, re-implemented).
FR_MAP = {
    "gfx": 0xC0330,          # sRegionMap_Gfx, LZ77 4bpp tiles
    "pal": 0xC02EC,          # sRegionMap_Pal, 16 x 16 colours, raw
    "tilemaps": (0xC035C, 0xC0370, 0xC0388, 0xC03A4),  # Kanto, Sevii 1-3, 4-5, 6-7: LZ77 30x20
    "sevii": 0xC00BC,        # sSeviiMapsecs[3][30]
    "sevii_cmp": 0xC0064,    # `cmp r0, #SEVII_MAPSEC_START - 1` + `bls` in InitRegionMap
    "corners": 0xC3D3C,      # sMapSectionTopLeftCorners {u16 x, u16 y}, from mapsec 0x58
    "dims": 0xC3D38,         # sMapSectionDimensions {u16 w, u16 h}
}
FR_FIRST_MAPSEC, FR_SECTIONS, MAPSEC_NONE_FR = 0x58, 109, 0xC5
GRID_OFFSET = 4  # the section tables count from 4 tiles into the 30x20 screen


def bgr555(c):
    return bytes(((c & 31) * 255 // 31, (c >> 5 & 31) * 255 // 31, (c >> 10 & 31) * 255 // 31, 255))


def render_4bpp_screen(tiles, palettes, tilemap, cols=30, rows=20):
    """RGBA of a text-mode BG screen: u16 entries = tile | hflip<<10 | vflip<<11 | pal<<12."""
    w, h = cols * 8, rows * 8
    out = bytearray(palettes[0][0] * (w * h))
    ntiles = len(tiles) // 32
    for ty in range(rows):
        for tx in range(cols):
            e = struct.unpack_from("<H", tilemap, (ty * cols + tx) * 2)[0]
            tile, hf, vf, pal = e & 0x3FF, e >> 10 & 1, e >> 11 & 1, e >> 12
            if tile >= ntiles:
                continue
            colors = palettes[pal]
            for py in range(8):
                row = tiles[tile * 32 + py * 4:tile * 32 + py * 4 + 4]
                dy = ty * 8 + (7 - py if vf else py)
                for px in range(8):
                    b = row[px >> 1]
                    idx = b >> 4 if px & 1 else b & 0xF
                    if idx:
                        dx = tx * 8 + (7 - px if hf else px)
                        o = (dy * w + dx) * 4
                        out[o:o + 4] = colors[idx]
    return bytes(out)


class RomData:
    def __init__(self, path):
        self.rom = load_rom(path)
        self.crc = "%08x" % (zlib.crc32(self.rom) & 0xFFFFFFFF)
        code = self.rom[0xAC:0xB0]
        self.engine = "em" if code in (b"BPEE", b"AXVE", b"AXPE") else "fr"
        self._sprites = {}
        self.t = self._load_tables()

    def _load_tables(self):
        cache = os.path.join(CACHE_DIR, self.crc + ".json")
        try:
            with open(cache) as f:
                t = json.load(f)
            if t.get("version") == CACHE_VERSION:
                return t
        except (OSError, ValueError):
            pass
        rom = self.rom
        t = {
            "version": CACHE_VERSION,
            "species": find_records(rom, _anchors("Bulbasaur", "Ivysaur", "Venusaur")),
            # Moves 3-4 differ between games (DoubleSlap / Double Slap / Doubleslap,
            # Odyssey's Bullet Punch for Comet Punch), so anchor on 1, 2, 5 and 6.
            "moves": find_records(rom, _anchors("Pound", "Karate Chop", None, None, "Mega Punch", "Pay Day")
                                  + _anchors("Pound", "Karate Chop", None, "Comet Punch")),
            "items": find_records(rom, _anchors("Master Ball", "Ultra Ball", "Great Ball")),
            # Type 1 is FIGHT or Fighting depending on the game, so skip it.
            "types": find_records(rom, _anchors("Normal", None, "Flying", "Poison", first=0), max_stride=16),
            # Base stats: HP Atk Def Spe SpA SpD, then type1 type2 (Grass, Poison).
            "base_stats": find_stats(rom, bytes([45, 49, 49, 45, 65, 65, 12, 3]),
                                     bytes([60, 62, 63, 60, 80, 80, 12, 3]), 0),
            # Battle moves: power type accuracy pp, one byte after the effect.
            "move_data": find_stats(rom, bytes([40, 0, 100, 35]), bytes([50, 1, 100, 25]), 1, 0x40),
            "move_desc": find_move_descriptions(rom),
            "mapsec_names": find_mapsec_names(rom, self.engine),
            "wild_headers": find_wild_headers(rom),
            "front_pics": _pick_front_table(rom, _species_tables(rom, find_sheet_tables(rom), (0x800, 0x1000), 6)),
            "palettes": (_species_tables(rom, find_palette_tables(rom), (0x20,), 4) or [None])[0],
        }
        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(cache, "w") as f:
                json.dump(t, f)
        except OSError:
            pass
        return t

    def _record_name(self, key, index, length):
        tbl = self.t.get(key)
        if not tbl:
            return None
        base, stride = tbl
        off = base + index * stride
        if index < 0 or off < 0 or off + length > len(self.rom):
            return None
        return decode_text(self.rom[off:off + length])

    def species_name(self, i):
        return self._record_name("species", i, 13) or "#%d" % i

    def move_name(self, i):
        return self._record_name("moves", i, 17) or "Move %d" % i

    def item_name(self, i):
        if i == 0:
            return ""
        return self._record_name("items", i, 15) or "Item %d" % i

    def type_name(self, i):
        raw = self._record_name("types", i, 8)
        if raw is None:
            return "?"
        return TYPE_ALIASES.get(raw.upper(), raw.capitalize())

    def species_types(self, i):
        tbl = self.t.get("base_stats")
        if not tbl:
            return []
        base, stride = tbl
        off = base + i * stride + 6
        if off + 2 > len(self.rom):
            return []
        t1, t2 = self.rom[off], self.rom[off + 1]
        return [self.type_name(t1)] + ([self.type_name(t2)] if t2 != t1 else [])

    def move_info(self, i):
        """Dict with type, power, accuracy, pp, effect chance and priority, or None.

        The first 8 bytes keep the vanilla layout in FireRed/Emerald, CFRU and
        Emerald Enhanced: effect power type accuracy pp chance target priority.
        """
        tbl = self.t.get("move_data")
        if not tbl:
            return None
        base, stride = tbl
        off = base + i * stride
        if off + 8 > len(self.rom):
            return None
        power, mtype, acc, pp, chance = self.rom[off + 1:off + 6]
        priority = struct.unpack_from("<b", self.rom, off + 7)[0]
        return {"type": self.type_name(mtype), "power": power, "acc": acc, "pp": pp,
                "chance": chance, "priority": priority}

    def move_description(self, i):
        base = self.t.get("move_desc")
        if base is None or i <= 0 or base + i * 4 + 4 > len(self.rom):
            return ""
        return _text_at_ptr(self.rom, base + i * 4) or ""

    def mapsec_name(self, mapsec):
        tbl = self.t.get("mapsec_names")
        if not tbl:
            return None
        base, stride, first = tbl
        off = base + (mapsec - first) * stride + stride - 4
        if mapsec < first or off + 4 > len(self.rom):
            return None
        return _short_text(self.rom, struct.unpack_from("<I", self.rom, off)[0])

    def wild_encounters(self, group, num):
        """{method: [(species, min_lv, max_lv, percent, note)]} for one map, merged per species."""
        tbl = self.t.get("wild_headers")
        if not tbl:
            return {}
        base, stride = tbl
        rom = self.rom
        off = base
        while off + stride <= len(rom) and rom[off] != 0xFF:
            if rom[off] == group and rom[off + 1] == num:
                break
            off += stride
        if off + stride > len(rom) or rom[off] == 0xFF:
            return {}
        out = {}
        for k, method in enumerate(("Grass", "Surfing", "Rock Smash", "Fishing")):
            info = self._ptr(off + 4 + k * 4)
            if info is None:
                continue
            mons = self._ptr(info + 4)
            if mons is None:
                continue
            merged = {}
            for slot, pct in enumerate(WILD_ODDS[method]):
                lo, hi, species = struct.unpack_from("<BBH", rom, mons + slot * 4)
                note = FISHING_RODS[slot] if method == "Fishing" else ""
                key = (species, note)
                if key in merged:
                    s, a, b, p, n = merged[key]
                    merged[key] = (s, min(a, lo), max(b, hi), p + pct, n)
                else:
                    merged[key] = (species, lo, hi, pct, note)
            out[method] = sorted(merged.values(), key=lambda e: (e[4], -e[3]))
        return out

    def _looks_like_map_header(self, off):
        if not 0 <= off < len(self.rom) - 0x1C:
            return False
        return all(0x08000000 <= struct.unpack_from("<I", self.rom, off + k)[0] < 0x0A000000 for k in (0, 4, 8))

    def map_id(self, header):
        """(group, num) of the map whose header gMapHeader copies, or None.

        gMapGroups[group][num] points at that header in ROM, so: find the header,
        the pointer to it, the group array holding that pointer, and that
        array's index in gMapGroups. Works without knowing any save layout.
        """
        key = bytes(header[:0x18])
        cache = self.__dict__.setdefault("_map_ids", {})
        if key in cache:
            return cache[key]
        cache[key] = result = self._map_id(key)
        return result

    def _map_id(self, key):
        rom = self.rom
        hdr = rom.find(key)
        if hdr < 0:
            return None
        q = rom.find(struct.pack("<I", 0x08000000 + hdr))
        while q != -1 and q % 4:
            q = rom.find(struct.pack("<I", 0x08000000 + hdr), q + 1)
        if q < 0:
            return None
        # Walk back to the nearest array start that gMapGroups points at.
        for num in range(256):
            start = q - num * 4
            if start < 0 or not self._looks_like_map_header(self._ptr(start) or -1):
                return None
            g = rom.find(struct.pack("<I", 0x08000000 + start))
            while g != -1:
                if g % 4 == 0 and self._is_group_table_entry(g):
                    first = g
                    while first >= 4 and self._is_group_table_entry(first - 4):
                        first -= 4
                    return (g - first) // 4, num
                g = rom.find(struct.pack("<I", 0x08000000 + start), g + 1)
        return None

    def _is_group_table_entry(self, off):
        """A gMapGroups entry points at an array whose first pointer is a map header."""
        arr = self._ptr(off)
        return arr is not None and self._looks_like_map_header(self._ptr(arr) or -1)

    def region_map(self):
        """{"images": [(w, h, rgba)], "sections": {mapsec: (image, x, y, w, h) in pixels}} or None.

        Drawing it takes seconds in Python, so the result is cached on disk per ROM.
        """
        if hasattr(self, "_region_map"):
            return self._region_map
        cache = os.path.join(CACHE_DIR, "%s-map-v%d.pickle" % (self.crc, CACHE_VERSION))
        try:
            with open(cache, "rb") as f:
                self._region_map = pickle.loads(zlib.decompress(f.read()))
            return self._region_map
        except (OSError, ValueError, pickle.UnpicklingError, zlib.error, EOFError):
            pass
        try:
            m = self._fr_region_map() if self.engine == "fr" else self._em_region_map()
        except (ValueError, IndexError, struct.error, TypeError):
            m = None
        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(cache, "wb") as f:
                f.write(zlib.compress(pickle.dumps(m)))
        except OSError:
            pass
        self._region_map = m
        return m

    def _em_region_map(self):
        """Emerald engine: the BG is an affine 64x64 map of 8bpp tiles; the visible
        map is its top-left 30x20 tiles. Found next to gRegionMapEntries (same
        source file) and confirmed by the code that loads them side by side."""
        rom = self.rom
        entries = (self.t.get("mapsec_names") or [None])[0]
        if entries is None:
            return None
        blobs = {}
        for off in range(max(0, entries - 0x30000), min(len(rom) - 4, entries + 0x4000), 4):
            if rom[off] != 0x10:
                continue
            size = rom[off + 1] | rom[off + 2] << 8 | rom[off + 3] << 16
            if size == 0x1000 or (size % 64 == 0 and 0x1000 <= size <= 0x10000):
                blobs[off] = size
        refs = {}

        def refs_of(off):
            if off not in refs:
                pat = re.escape(struct.pack("<I", 0x08000000 + off))
                refs[off] = [m.start() for m in re.finditer(pat, rom) if m.start() % 4 == 0]
            return refs[off]

        for tm_off, tm_size in blobs.items():
            if tm_size != 0x1000 or not refs_of(tm_off):
                continue
            try:
                tm = lz77(rom, tm_off)
            except (ValueError, IndexError):
                continue  # looked like LZ77, wasn't
            for gfx_off, gfx_size in blobs.items():
                if gfx_off == tm_off or gfx_size % 64 or max(tm) >= gfx_size // 64:
                    continue
                near = [(a, b) for a in refs_of(gfx_off) for b in refs[tm_off] if abs(a - b) < 0x100]
                if not near:
                    continue
                try:
                    tiles = lz77(rom, gfx_off)
                except (ValueError, IndexError):
                    continue
                pal_off = self._em_palette_near(near[0][0], gfx_off)
                return self._em_render(tiles, tm, pal_off, entries)
        return None

    def _em_palette_near(self, code_ref, gfx_off):
        """The raw palette the same code loads; in ROM it ends where the tiles begin."""
        for o in range(code_ref - 0x100, code_ref + 0x100, 4):
            p = struct.unpack_from("<I", self.rom, o)[0] - 0x08000000
            if 0 < gfx_off - p <= 0x200 and (gfx_off - p) % 2 == 0 and self.rom[p] != 0x10:
                return p
        return gfx_off - 0x40

    def _em_render(self, tiles, tm, pal_off, entries):
        first = 0x70  # LoadPalette(sRegionMapBg_Pal, BG_PLTT_ID(7), ...)
        pal = [bgr555(struct.unpack_from("<H", self.rom, pal_off + k * 2)[0])
               for k in range(min(0x90, (len(self.rom) - pal_off) // 2))]
        backdrop = pal[0]
        w, h = 240, 160
        out = bytearray(backdrop * (w * h))
        for ty in range(20):
            for tx in range(30):
                t = tm[ty * 64 + tx]
                for py in range(8):
                    row = tiles[t * 64 + py * 8:t * 64 + py * 8 + 8]
                    for px, i in enumerate(row):
                        if i >= first and i - first < len(pal):
                            o = ((ty * 8 + py) * w + tx * 8 + px) * 4
                            out[o:o + 4] = pal[i - first]
        sections = {}
        for ms in range(0x100):
            off = entries + ms * 8
            if off + 8 > len(self.rom):
                break
            if _short_text(self.rom, struct.unpack_from("<I", self.rom, off + 4)[0]) is None:
                break  # past the end of gRegionMapEntries
            x, y, sw, sh = self.rom[off:off + 4]
            if sw and sh and x < 30 and y < 20:
                # MAPCURSOR_X_MIN / Y_MIN: the cursor grid starts 1 tile right, 2 down.
                sections[ms] = (0, (x + 1) * 8, (y + 2) * 8, sw * 8, sh * 8)
        return {"images": [(w, h, bytes(out))], "sections": sections}

    def _fr_region_map(self):
        rom = self.rom
        if rom[0xAC:0xB0] != b"BPRE" or rom[0xBC] != 0:
            return None
        ptr = self._ptr
        tiles = lz77(rom, ptr(FR_MAP["gfx"]))
        if not tiles or len(tiles) % 32:
            return None
        pal_off = ptr(FR_MAP["pal"])
        palettes = [[bgr555(struct.unpack_from("<H", rom, pal_off + (p * 16 + k) * 2)[0]) for k in range(16)]
                    for p in range(16)]
        map_offs = [ptr(o) for o in FR_MAP["tilemaps"]]
        if None in map_offs:
            return None
        distinct = list(dict.fromkeys(map_offs))
        images = []
        for off in distinct:
            tm = lz77(rom, off)
            if len(tm) < 30 * 20 * 2:  # Unbound's ends early; the rest is the border tile
                tm = tm[:len(tm) // 2 * 2] + tm[:2] * (30 * 20 - len(tm) // 2)
            images.append((240, 160, render_4bpp_screen(tiles, palettes, tm)))
        image_of = [distinct.index(o) for o in map_offs]

        cmp = rom[FR_MAP["sevii_cmp"]:FR_MAP["sevii_cmp"] + 4]
        sevii_start = cmp[0] + 1 if cmp[1] == 0x28 and cmp[3] == 0xD9 else 0x100
        sevii = rom[ptr(FR_MAP["sevii"]):ptr(FR_MAP["sevii"]) + 90]

        def region_of(mapsec):
            if mapsec < sevii_start:
                return 0
            for j in range(3):
                for i in range(30):
                    m = sevii[j * 30 + i]
                    if m == MAPSEC_NONE_FR:
                        break
                    if m == mapsec:
                        return j + 1
            return 0

        corners, dims = ptr(FR_MAP["corners"]), ptr(FR_MAP["dims"])
        sections = {}
        for i in range(FR_SECTIONS):
            x, y = struct.unpack_from("<HH", rom, corners + i * 4)
            w, h = struct.unpack_from("<HH", rom, dims + i * 4)
            if (x or y) and w and h:  # {0,0}: not on the map (dungeons, buildings)
                sections[FR_FIRST_MAPSEC + i] = (image_of[region_of(FR_FIRST_MAPSEC + i)],
                                                 (x + GRID_OFFSET) * 8, (y + GRID_OFFSET) * 8, w * 8, h * 8)
        return {"images": images, "sections": sections}

    def pocket_names(self):
        """The bag's pocket names in pocket order, from the ROM, or None.

        Found as a run of string pointers that holds "Key Items" and a "...Balls"
        entry and starts with "Items" (Emerald Enhanced: Items, Medicine,
        Valuables, Poke Balls, TMs & HMs, Berries, Key Items, Mega Stones).
        """
        if "_pocket_names" not in self.__dict__:
            self._pocket_names = self._find_pocket_names()
        return self._pocket_names

    def _find_pocket_names(self):
        rom = self.rom
        best = None
        for word in ("Key Items", "KEY ITEMS"):
            enc = encode_text(word) + b"\xFF"
            pos = rom.find(enc)
            while pos != -1:
                ptr = struct.pack("<I", 0x08000000 + pos)
                q = rom.find(ptr)
                while q != -1:
                    if q % 4 == 0:
                        start = q
                        while start >= 4 and _short_text(rom, struct.unpack_from("<I", rom, start - 4)[0]):
                            start -= 4
                        names = []
                        while len(names) < 12:
                            t = _short_text(rom, struct.unpack_from("<I", rom, start + len(names) * 4)[0])
                            if not t:
                                break
                            names.append(t)
                        if (names and "item" in names[0].lower() and any("ball" in n.lower() for n in names)
                                and (best is None or len(names) > len(best))):
                            best = names
                    q = rom.find(ptr, q + 1)
                pos = rom.find(enc, pos + 1)
        return best

    def item_description(self, i):
        tbl = self.t.get("items")
        if not tbl or i <= 0:
            return ""
        base, stride = tbl
        if "item_desc_off" not in self.t:
            self.t["item_desc_off"] = self._find_item_desc_off(base, stride)
        k = self.t["item_desc_off"]
        if k is None or base + i * stride + k + 4 > len(self.rom):
            return ""
        return _text_at_ptr(self.rom, base + i * stride + k) or ""

    def _find_item_desc_off(self, base, stride):
        """The record field that points at a sentence for the first few items."""
        for k in range(16, stride - 3, 4):
            texts = [_text_at_ptr(self.rom, base + i * stride + k, 120) for i in range(1, 6)]
            if all(t and len(t) > 12 and " " in t for t in texts):
                return k
        return None

    def _ptr(self, off):
        p = struct.unpack_from("<I", self.rom, off)[0]
        return p - 0x08000000 if 0x08000000 <= p < 0x08000000 + len(self.rom) else None

    def sprite_rgba(self, species):
        """64x64 RGBA bytes of the front sprite (first frame), or None."""
        if species in self._sprites:
            return self._sprites[species]
        rgba = None
        pics, pals = self.t.get("front_pics"), self.t.get("palettes")
        if pics is not None and pals is not None:
            try:
                rgba = self._decode_sprite(pics + species * 8, pals + species * 8)
            except (ValueError, IndexError, struct.error):
                rgba = None
        self._sprites[species] = rgba
        return rgba

    def _decode_sprite(self, pic_entry, pal_entry):
        pic_off, pal_off = self._ptr(pic_entry), self._ptr(pal_entry)
        if pic_off is None or pal_off is None:
            return None
        tiles = lz77(self.rom, pic_off)
        pal_raw = lz77(self.rom, pal_off)
        palette = []
        for k in range(16):
            c = struct.unpack_from("<H", pal_raw, k * 2)[0]
            r, g, b = (c & 31) * 255 // 31, (c >> 5 & 31) * 255 // 31, (c >> 10 & 31) * 255 // 31
            palette.append(bytes((r, g, b, 0 if k == 0 else 255)))
        out = bytearray(64 * 64 * 4)
        for tile in range(64):
            tx, ty = tile % 8 * 8, tile // 8 * 8
            for row in range(8):
                src = tile * 32 + row * 4
                dst = ((ty + row) * 64 + tx) * 4
                for col in range(4):
                    b = tiles[src + col]
                    out[dst + col * 8:dst + col * 8 + 4] = palette[b & 0xF]
                    out[dst + col * 8 + 4:dst + col * 8 + 8] = palette[b >> 4]
        return bytes(out)
