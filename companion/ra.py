# SPDX-License-Identifier: GPL-2.0-or-later
"""RetroArch Network Control Interface client (UDP), memory reads only."""

import socket

# One request is answered once per emulated frame, so read in big chunks.
CHUNK = 2048


class RAError(Exception):
    """RetroArch did not answer (not running, or network commands off)."""


class RAReadError(RAError):
    """RetroArch answered, but that address isn't readable (bad guess, not a lost connection)."""


class RetroArch:
    def __init__(self, host="127.0.0.1", port=55355, timeout=0.5):
        self.addr = (host, port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(timeout)

    def query(self, cmd, prefix=None, tries=2):
        """Sends cmd and waits for its reply; a single lost UDP packet is retried."""
        self.sock.sendto(cmd.encode("ascii"), self.addr)
        while True:
            try:
                data, _ = self.sock.recvfrom(65535)
            except (socket.timeout, OSError) as e:
                if tries > 1:
                    return self.query(cmd, prefix, tries - 1)
                raise RAError("no reply to %r: %s" % (cmd.split()[0], e))
            text = data.decode("ascii", "replace").strip()
            # Skip late replies to an earlier request that timed out.
            if prefix is None or text.startswith(prefix):
                return text

    def status(self):
        return self.query("GET_STATUS", "GET_STATUS")

    def read(self, addr, n):
        out = bytearray()
        while n > 0:
            k = min(n, CHUNK)
            parts = self.query("READ_CORE_MEMORY %x %d" % (addr, k), "READ_CORE_MEMORY %x " % addr).split()
            if parts[2] == "-1":
                raise RAReadError("read %08X: %s" % (addr, " ".join(parts[3:])))
            got = bytes(int(x, 16) for x in parts[2:])
            if not got:
                raise RAReadError("read %08X: empty reply" % addr)
            out += got
            addr += len(got)
            n -= len(got)
        return bytes(out)
