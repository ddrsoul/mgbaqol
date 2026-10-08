#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Dumps GBA EWRAM and IWRAM from the running game: dump.py NAME -> /tmp/NAME.ewram, /tmp/NAME.iwram."""

import sys

sys.path.insert(0, "/storage/mgbaqol-dev/share")
from ra import RetroArch  # noqa: E402

ra = RetroArch()
for region, base, size in (("ewram", 0x02000000, 0x40000), ("iwram", 0x03000000, 0x8000)):
    with open("/tmp/%s.%s" % (sys.argv[1], region), "wb") as f:
        f.write(ra.read(base, size))
print("ok")
