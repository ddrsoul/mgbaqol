# SPDX-License-Identifier: GPL-2.0-or-later
"""Gen 3 text encoding and party Pokemon decoding."""

import struct

CHARMAP = {0x00: " ", 0xAB: "!", 0xAC: "?", 0xAD: ".", 0xAE: "-", 0xB0: "…",
           0xB1: "“", 0xB2: "”", 0xB3: "‘", 0xB4: "'", 0xB5: "♂", 0xB6: "♀",
           0xB8: ",", 0xBA: "/", 0x1B: "é", 0x5C: "(", 0x5D: ")", 0x2D: "&", 0x35: "=",
           0xF0: ":", 0xFA: " ", 0xFB: " ", 0xFE: " "}  # FA/FB/FE: line and page breaks
for _i in range(10):
    CHARMAP[0xA1 + _i] = str(_i)
for _i in range(26):
    CHARMAP[0xBB + _i] = chr(ord("A") + _i)
    CHARMAP[0xD5 + _i] = chr(ord("a") + _i)
ENCODE = {v: k for k, v in CHARMAP.items()}
ENCODE.update({'"': 0xB1, "'": 0xB4, " ": 0x00})

MON_SIZE = 100

# Substructure order (Growth, Attacks, EVs, Misc) by personality % 24.
ORDERS = ["GAEM", "GAME", "GEAM", "GEMA", "GMAE", "GMEA",
          "AGEM", "AGME", "AEGM", "AEMG", "AMGE", "AMEG",
          "EGAM", "EGMA", "EAGM", "EAMG", "EMGA", "EMAG",
          "MGAE", "MGEA", "MAGE", "MAEG", "MEGA", "MEAG"]


def decode_text(raw):
    out = []
    for c in raw:
        if c == 0xFF:
            break
        out.append(CHARMAP.get(c, "?"))
    return " ".join("".join(out).split())


def encode_text(s):
    return bytes(ENCODE[ch] for ch in s)


def status_name(s):
    if s & 0x7:
        return "SLP"
    for bit, name in ((0x8, "PSN"), (0x10, "BRN"), (0x20, "FRZ"), (0x40, "PAR"), (0x80, "TOX")):
        if s & bit:
            return name
    return ""


def decode_mon(raw):
    """Returns a dict for a 100-byte party Pokemon, or None for an empty slot."""
    pid, otid = struct.unpack_from("<II", raw, 0)
    if pid == 0 and otid == 0:
        return None
    sub, valid = _substructs(raw, pid, otid)
    species, item, exp = struct.unpack_from("<HHI", sub["G"], 0)
    hp, max_hp, atk, dfn, spe, spa, spd = struct.unpack_from("<7H", raw, 86)
    shiny_value = (otid >> 16) ^ (otid & 0xFFFF) ^ (pid >> 16) ^ (pid & 0xFFFF)
    return {
        "pid": pid,
        "nick": decode_text(raw[8:18]),
        "valid": valid,
        "species": species,
        "item": item,
        "exp": exp,
        "moves": list(struct.unpack_from("<4H", sub["A"], 0)),
        "pp": list(sub["A"][8:12]),
        "status": struct.unpack_from("<I", raw, 80)[0],
        "level": raw[84],
        "hp": hp,
        "max_hp": max_hp,
        "stats": {"Atk": atk, "Def": dfn, "SpA": spa, "SpD": spd, "Spe": spe},
        "shiny": shiny_value < 8,
        "is_egg": bool(struct.unpack_from("<I", sub["M"], 4)[0] & (1 << 30)),
    }


def _substructs(raw, pid, otid):
    """The four 12-byte substructures, and whether they look right.

    Retail games XOR them with personality ^ OT id and shuffle them by
    personality % 24, guarded by a checksum. Some hacks (Pokemon Odyssey)
    store them plain, in fixed order, without keeping the checksum; those
    are accepted when every field is in range.
    """
    key = pid ^ otid
    dec = b"".join(struct.pack("<I", struct.unpack_from("<I", raw, 32 + i)[0] ^ key) for i in range(0, 48, 4))
    order = ORDERS[pid % 24]
    sub = {order[i]: dec[i * 12:(i + 1) * 12] for i in range(4)}
    if (sum(struct.unpack("<24H", dec)) & 0xFFFF) == struct.unpack_from("<H", raw, 28)[0]:
        return sub, True
    plain = raw[32:80]
    psub = {"GAEM"[i]: plain[i * 12:(i + 1) * 12] for i in range(4)}
    species = struct.unpack_from("<H", psub["G"], 0)[0]
    moves = struct.unpack_from("<4H", psub["A"], 0)
    pp = psub["A"][8:12]
    if 0 < species < 2048 and moves[0] and all(m < 1024 for m in moves) and all(p <= 64 for p in pp):
        return psub, True
    return sub, False


def plausible(m):
    return (m is not None and m["valid"] and 1 <= m["level"] <= 100
            and 0 < m["max_hp"] and m["hp"] <= m["max_hp"] and 0 < m["species"] < 2048)


def decode_party(raw, count):
    """Decodes up to `count` slots; returns None if any slot looks torn."""
    party = []
    for slot in range(min(count, 6)):
        m = decode_mon(raw[slot * MON_SIZE:(slot + 1) * MON_SIZE])
        if not plausible(m):
            return None
        party.append(m)
    return party
