#!/bin/sh
# Builds the test install into build/mgbaqol-dev (the layout install.sh expects).
set -e
cd "$(dirname "$0")/.."
OUT=build/mgbaqol-dev
rm -rf "${OUT}"
mkdir -p "${OUT}/share" "${OUT}/rocknix"
cp companion/*.py "${OUT}/share/"
cp rocknix/start_mgbaqol.sh rocknix/mgbaqol_libretro.info "${OUT}/rocknix/"
cp test-install/install.sh test-install/uninstall.sh test-install/patch_runemu.py \
   test-install/autostart-mgbaqol-dev "${OUT}/"
echo "${OUT}"
