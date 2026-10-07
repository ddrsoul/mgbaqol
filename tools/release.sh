#!/bin/sh
# Makes build/mgbaqol-test-install-VERSION.zip: unpack it to /storage on the console.
set -e
cd "$(dirname "$0")/.."
VERSION=${1:?usage: tools/release.sh VERSION}
sh tools/build.sh >/dev/null
python3 - "${VERSION}" <<'PY'
import os, sys, zipfile
out = "build/mgbaqol-test-install-%s.zip" % sys.argv[1]
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for root, _, files in os.walk("build/mgbaqol-dev"):
        for name in sorted(files):
            path = os.path.join(root, name)
            info = zipfile.ZipInfo.from_file(path, os.path.relpath(path, "build"))
            if name.endswith(".sh") or name.startswith("autostart") or name == "patch_runemu.py":
                info.external_attr = 0o100755 << 16
            else:
                info.external_attr = 0o100644 << 16
            with open(path, "rb") as f:
                z.writestr(info, f.read(), zipfile.ZIP_DEFLATED)
print(out)
PY
