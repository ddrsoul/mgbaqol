#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-or-later
# Removes the mgba-qol test install. --purge also deletes its files, caches and dev probes.

grep -q " /usr/bin/runemu.sh " /proc/mounts && umount /usr/bin/runemu.sh
rm -f /storage/.config/autostart/mgbaqol-dev
rm -f /storage/cores/mgbaqol_libretro.so /storage/cores/mgbaqol_libretro.info
ES_USER=/storage/.config/emulationstation/es_systems.cfg
if [ ! -L "${ES_USER}" ]; then
  rm -f "${ES_USER}"
  ln -s /usr/config/emulationstation/es_systems.cfg "${ES_USER}"
fi
if [ "$1" = "--purge" ]; then
  rm -rf /storage/.config/mgbaqol /storage/mgbaqol /storage/mgbaqol-probe /storage/mgbaqol-dev
fi
echo "mgba-qol test install removed. Restart EmulationStation: systemctl restart essway"
