#!/usr/bin/env python3
"""Dev tool: renders the ROM's region map(s) with section frames. region_png.py ROM OUT_PREFIX"""
import sys
sys.path.insert(0, "/storage/mgbaqol-dev/share")
import romdata  # noqa: E402
from sprite_sheet import write_png  # noqa: E402

r = romdata.RomData(sys.argv[1])
m = r.region_map()
if not m:
    sys.exit("no region map")
print("images", len(m["images"]), "sections", len(m["sections"]))
for idx, (w, h, rgba) in enumerate(m["images"]):
    img = bytearray(rgba)
    for mapsec, (im, x, y, sw, sh) in m["sections"].items():
        if im != idx:
            continue
        for px in range(x, x + sw):
            for py in (y, y + sh - 1):
                if 0 <= px < w and 0 <= py < h:
                    img[(py * w + px) * 4:(py * w + px) * 4 + 4] = b"\xff\x30\x30\xff"
        for py in range(y, y + sh):
            for px in (x, x + sw - 1):
                if 0 <= px < w and 0 <= py < h:
                    img[(py * w + px) * 4:(py * w + px) * 4 + 4] = b"\xff\x30\x30\xff"
    write_png("%s-%d.png" % (sys.argv[2], idx), w, h, bytes(img))
for mapsec in list(m["sections"])[:6]:
    print(hex(mapsec), r.mapsec_name(mapsec), m["sections"][mapsec])
