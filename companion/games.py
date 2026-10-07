# SPDX-License-Identifier: GPL-2.0-or-later
"""Per-game RAM locations. Matched on the ROM header (game code + title)."""

PROFILES = [
    # name, game code, title prefix, gPlayerParty, gPlayerPartyCount
    ("Emerald Enhanced", "BPEE", "EE ", 0x0203863C, 0x02038639),
    ("Pokemon Emerald", "BPEE", "POKEMON EMER", 0x020244EC, 0x020244E9),
    ("Pokemon FireRed", "BPRE", "POKEMON FIRE", 0x02024284, 0x02024029),
    ("Pokemon LeafGreen", "BPGE", "POKEMON LEAF", 0x02024284, 0x02024029),
    ("Pokemon Ruby", "AXVE", "POKEMON RUBY", 0x03004360, 0x03004350),
    ("Pokemon Sapphire", "AXPE", "POKEMON SAPP", 0x03004360, 0x03004350),
]


def header(rom):
    title = rom[0xA0:0xAC].decode("ascii", "replace").rstrip("\0 ")
    code = rom[0xAC:0xB0].decode("ascii", "replace")
    return title, code


def match(rom):
    """Returns (name, party_addr, count_addr) or None for an unknown game."""
    title, code = header(rom)
    for name, pcode, prefix, party, count in PROFILES:
        if code == pcode and (title + " ").startswith(prefix):
            return name, party, count
    return None
