#!/usr/bin/env python3
"""Dev tool: renders sprites from every candidate sheet table into one PNG.

  python3 sprite_sheet.py ROM OUT.png [species ...]
Rows = candidate tables (in ROM order), columns = species. Uses the picked palette table.
"""

import struct
import sys
import zlib

sys.path.insert(0, "/storage/mgbaqol/companion")
import romdata  # noqa: E402


def write_png(path, w, h, rgba):
    raw = b"".join(b"\0" + rgba[y * w * 4:(y + 1) * w * 4] for y in range(h))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


def main():
    rom_path, out = sys.argv[1], sys.argv[2]
    species = [int(s) for s in sys.argv[3:]] or [1, 4, 7, 25, 156, 261]
    r = romdata.RomData(rom_path)
    tables = romdata.find_sheet_tables(r.rom)
    pals = r.t["palettes"]
    print("sheet tables:", [hex(t) for t in tables], "palettes:", hex(pals))
    w, h = 64 * len(species), 64 * len(tables)
    img = bytearray(b"\x30\x30\x40\xff" * (w * h))
    for row, table in enumerate(tables):
        print("row %d: 0x%X len %d" % (row, table, romdata._table_len(r.rom, table, (0x800, 0x1000), 6)))
        for col, sp in enumerate(species):
            try:
                rgba = r._decode_sprite(table + sp * 8, pals + sp * 8)
            except Exception as e:  # noqa: BLE001 - dev tool
                print("  species %d: %s" % (sp, e))
                continue
            if rgba is None:
                print("  species %d: bad pointer" % sp)
                continue
            for y in range(64):
                for x in range(64):
                    px = rgba[(y * 64 + x) * 4:(y * 64 + x) * 4 + 4]
                    if px[3]:
                        o = ((row * 64 + y) * w + col * 64 + x) * 4
                        img[o:o + 4] = px
    write_png(out, w, h, bytes(img))
    base, stride = r.t["base_stats"]
    for sp in species:
        rec = r.rom[base + sp * stride:base + (sp + 1) * stride]
        print("base stats %4d %-10s %s" % (sp, r.species_name(sp), rec.hex(" ")))


if __name__ == "__main__":
    main()
