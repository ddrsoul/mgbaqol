#!/usr/bin/env python3
"""mgba-qol probe: reads the Gen 3 party from a running RetroArch over UDP.

Needs RetroArch with network_cmd_enable = "true" and a Gen 3 Pokemon game
running on the mgba core. --rom adds species names (read from the ROM file).

  python3 probe_mem.py --rom "/storage/roms/gba/Pokemon FireRed.gba"
  python3 probe_mem.py --scan        # search RAM if the game code is unknown
"""

import argparse
import socket
import struct
import sys
import time
import zipfile

CHARMAP = {0x00: " ", 0xAB: "!", 0xAC: "?", 0xAD: ".", 0xAE: "-", 0xB0: "~",
           0xB1: '"', 0xB2: '"', 0xB3: "'", 0xB4: "'", 0xB5: "(m)", 0xB6: "(f)",
           0xB8: ",", 0xBA: "/", 0x1B: "e"}
for _i in range(10):
    CHARMAP[0xA1 + _i] = str(_i)
for _i in range(26):
    CHARMAP[0xBB + _i] = chr(ord("A") + _i)
    CHARMAP[0xD5 + _i] = chr(ord("a") + _i)
ENCODE = {v: k for k, v in CHARMAP.items() if len(v) == 1}

# gPlayerParty / gPlayerPartyCount for the English releases.
PARTY = {
    "BPRE": (0x02024284, 0x02024029, "FireRed"),
    "BPGE": (0x02024284, 0x02024029, "LeafGreen"),
    "BPEE": (0x020244EC, 0x020244E9, "Emerald"),
    "AXVE": (0x03004360, 0x03004350, "Ruby"),
    "AXPE": (0x03004360, 0x03004350, "Sapphire"),
}

# Substructure order (Growth, Attacks, EVs, Misc) by personality % 24.
ORDERS = ["GAEM", "GAME", "GEAM", "GEMA", "GMAE", "GMEA",
          "AGEM", "AGME", "AEGM", "AEMG", "AMGE", "AMEG",
          "EGAM", "EGMA", "EAGM", "EAMG", "EMGA", "EMAG",
          "MGAE", "MGEA", "MAGE", "MAEG", "MEGA", "MEAG"]

MON_SIZE = 100


def decode_text(raw):
    out = []
    for c in raw:
        if c == 0xFF:
            break
        out.append(CHARMAP.get(c, "?"))
    return "".join(out)


def encode_text(s):
    return bytes(ENCODE[ch] for ch in s)


def status_str(s):
    if s & 0x7:
        return "SLP"
    for bit, name in ((0x8, "PSN"), (0x10, "BRN"), (0x20, "FRZ"), (0x40, "PAR"), (0x80, "TOX")):
        if s & bit:
            return name
    return "OK"


class RA:
    def __init__(self, host, port, timeout):
        self.addr = (host, port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(timeout)

    def query(self, cmd, prefix=None):
        self.sock.sendto(cmd.encode("ascii"), self.addr)
        while True:
            data, _ = self.sock.recvfrom(65535)
            text = data.decode("ascii", "replace").strip()
            # Skip late replies to an earlier request that timed out.
            if prefix is None or text.startswith(prefix):
                return text

    def read(self, addr, n, chunk):
        out = bytearray()
        while n > 0:
            k = min(n, chunk)
            prefix = "READ_CORE_MEMORY %x " % addr
            parts = self.query("READ_CORE_MEMORY %x %d" % (addr, k), prefix).split()
            if parts[2] == "-1":
                raise RuntimeError("read %08X: %s" % (addr, " ".join(parts[3:])))
            got = bytes(int(x, 16) for x in parts[2:])
            if not got:
                raise RuntimeError("read %08X: empty reply" % addr)
            out += got
            addr += len(got)
            n -= len(got)
        return bytes(out)


def decode_mon(raw):
    pid, otid = struct.unpack_from("<II", raw, 0)
    if pid == 0 and otid == 0:
        return None
    key = pid ^ otid
    dec = b"".join(struct.pack("<I", struct.unpack_from("<I", raw, 32 + i)[0] ^ key)
                   for i in range(0, 48, 4))
    checksum = struct.unpack_from("<H", raw, 28)[0]
    order = ORDERS[pid % 24]
    sub = {order[i]: dec[i * 12:(i + 1) * 12] for i in range(4)}
    species, item = struct.unpack_from("<HH", sub["G"], 0)
    hp, max_hp = struct.unpack_from("<HH", raw, 86)
    return {
        "pid": pid,
        "nick": decode_text(raw[8:18]),
        "checksum_ok": (sum(struct.unpack("<24H", dec)) & 0xFFFF) == checksum,
        "species": species,
        "item": item,
        "moves": struct.unpack_from("<4H", sub["A"], 0),
        "pp": tuple(sub["A"][8:12]),
        "status": struct.unpack_from("<I", raw, 80)[0],
        "level": raw[84],
        "hp": hp,
        "max_hp": max_hp,
    }


def plausible(m):
    return (m is not None and m["checksum_ok"] and 1 <= m["level"] <= 100
            and 0 < m["max_hp"] and m["hp"] <= m["max_hp"] and 0 < m["species"] < 2000)


def load_rom(path):
    if path.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".gba"))
            return z.read(name)
    with open(path, "rb") as f:
        return f.read()


def species_names(rom):
    """Finds the species name records by Bulbasaur/Ivysaur/Venusaur spacing.

    Vanilla keeps an 11-byte name array; hacks (CFRU, pokeemerald-expansion)
    use other strides or embed the name in a bigger per-species struct.
    """
    for first, second, third in (("BULBASAUR", "IVYSAUR", "VENUSAUR"),
                                 ("Bulbasaur", "Ivysaur", "Venusaur")):
        needle = encode_text(first) + b"\xFF"
        pos = rom.find(needle)
        while pos != -1:
            for stride in range(11, 0x200):
                if (rom.startswith(encode_text(second) + b"\xFF", pos + stride)
                        and rom.startswith(encode_text(third) + b"\xFF", pos + 2 * stride)):
                    base = pos - stride
                    print("species names: ROM offset 0x%06X, stride %d" % (base, stride))
                    return lambda i: decode_text(rom[base + i * stride:base + i * stride + 13])
            pos = rom.find(needle, pos + 1)
    return None


def print_party(ra, party_addr, count, chunk, names):
    raw = ra.read(party_addr, MON_SIZE * 6, chunk)
    for slot in range(6):
        m = decode_mon(raw[slot * MON_SIZE:(slot + 1) * MON_SIZE])
        if m is None:
            print("  slot %d: empty" % (slot + 1))
            continue
        name = names(m["species"]) if names else "?"
        print("  slot %d: %-10s species=%3d (%s) Lv%-3d HP %3d/%-3d %s item=%d moves=%s pp=%s checksum=%s"
              % (slot + 1, m["nick"], m["species"], name, m["level"], m["hp"], m["max_hp"],
                 status_str(m["status"]), m["item"], list(m["moves"]), list(m["pp"]),
                 "OK" if m["checksum_ok"] else "BAD"))


def scan(ra, chunk):
    regions = [(0x02000000, 0x40000, "EWRAM"), (0x03000000, 0x8000, "IWRAM")]
    for base, size, label in regions:
        t0 = time.monotonic()
        mem = ra.read(base, size, chunk)
        dt = time.monotonic() - t0
        print("%s: read %d KB in %.1f s" % (label, size // 1024, dt))
        for off in range(0, size - MON_SIZE * 2, 4):
            first = decode_mon(mem[off:off + MON_SIZE])
            if not plausible(first):
                continue
            run = 1
            while run < 6 and plausible(decode_mon(mem[off + run * MON_SIZE:off + (run + 1) * MON_SIZE])):
                run += 1
            print("  candidate 0x%08X: %d valid mons in a row, first Lv%d species=%d"
                  % (base + off, run, first["level"], first["species"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=55355)
    ap.add_argument("--timeout", type=float, default=0.5)
    ap.add_argument("--chunk", type=int, default=256, help="bytes per READ_CORE_MEMORY")
    ap.add_argument("--rom", help="ROM path, for species names")
    ap.add_argument("--scan", action="store_true", help="search RAM for the party")
    ap.add_argument("--party", type=lambda s: int(s, 16), help="party address override (hex)")
    args = ap.parse_args()

    ra = RA(args.host, args.port, args.timeout)

    print("== 1. network commands")
    try:
        print("VERSION    ->", ra.query("VERSION"))
        print("GET_STATUS ->", ra.query("GET_STATUS", "GET_STATUS"))
    except socket.timeout:
        print("RESULT: FAIL no reply on UDP %d. Is network_cmd_enable = \"true\" and a game running?" % args.port)
        return 1

    print("\n== 2. ROM header via the core memory map")
    try:
        hdr = ra.read(0x080000A0, 32, args.chunk)
    except (RuntimeError, socket.timeout) as e:
        print("RESULT: FAIL", e)
        return 1
    title = hdr[0:12].decode("ascii", "replace").rstrip("\0")
    code = hdr[12:16].decode("ascii", "replace")
    print("title=%r code=%s revision=%d" % (title, code, hdr[0x1C]))

    names = None
    if args.rom:
        names = species_names(load_rom(args.rom))
        if names is None:
            print("species names table not found in ROM (hack or non-English release?)")

    if args.scan:
        print("\n== 3. RAM scan")
        scan(ra, args.chunk)
        return 0

    if args.party is not None:
        party_addr, count_addr, game = args.party, args.party - 4, "override"
        print("bytes before party:", ra.read(args.party - 8, 8, args.chunk).hex(" "))
    elif code not in PARTY:
        print("RESULT: game code %s is not in the table; rerun with --scan" % code)
        return 1
    else:
        party_addr, count_addr, game = PARTY[code]

    print("\n== 3. party (%s, gPlayerParty at 0x%08X)" % (game, party_addr))
    count = ra.read(count_addr, 1, args.chunk)[0]
    print("party count:", count)
    print_party(ra, party_addr, count, args.chunk, names)

    print("\n== 4. latency")
    n = 20
    t0 = time.monotonic()
    for _ in range(n):
        ra.read(party_addr, MON_SIZE * 6, args.chunk)
    dt = (time.monotonic() - t0) / n
    print("full party read (600 bytes, %d-byte chunks): %.1f ms" % (args.chunk, dt * 1000))
    try:
        t0 = time.monotonic()
        ra.read(party_addr, MON_SIZE * 6, 600)
        print("single 600-byte request: OK, %.1f ms" % ((time.monotonic() - t0) * 1000))
    except (RuntimeError, socket.timeout) as e:
        print("single 600-byte request: FAIL", e)

    print("\nRESULT: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
