#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-or-later
# mgba-qol test install for ROCKNIX, without a firmware rebuild.
# Unpack to /storage/mgbaqol-dev and run once; it then re-runs at every boot
# from /storage/.config/autostart. Safe to run again.
# Undo: /storage/mgbaqol-dev/uninstall.sh [--purge]

D=$(cd "$(dirname "$0")" && pwd)
LOG=/var/log/mgbaqol-install.log
ES_SYS=/usr/config/emulationstation/es_systems.cfg
ES_USER=/storage/.config/emulationstation/es_systems.cfg

log() {
  echo "$*"
  echo "$*" >>"${LOG}"
}

echo "== $(date) install from ${D}" >>"${LOG}"

if grep -q "<core>mgbaqol</core>" "${ES_SYS}"; then
  log "This firmware already ships mgba-qol; the test install is not needed."
  exit 0
fi

# Run again at every boot (the runemu.sh mount does not survive a reboot).
mkdir -p /storage/.config/autostart
cp "${D}/autostart-mgbaqol-dev" /storage/.config/autostart/mgbaqol-dev
chmod +x /storage/.config/autostart/mgbaqol-dev

# Core alias + info in the /storage/cores layer of the /tmp/cores overlay.
mkdir -p /storage/cores
ln -sf mgba_libretro.so /storage/cores/mgbaqol_libretro.so
cp "${D}/rocknix/mgbaqol_libretro.info" /storage/cores/

# Start script pointing at this folder's copy of the companion.
sed "s|/usr/share/mgbaqol/main.py|${D}/share/main.py|" "${D}/rocknix/start_mgbaqol.sh" >"${D}/start_mgbaqol.sh"
chmod +x "${D}/start_mgbaqol.sh"

# runemu.sh with the hook: patch the firmware's own copy, mount it over.
grep -q " /usr/bin/runemu.sh " /proc/mounts && umount /usr/bin/runemu.sh
python3 "${D}/patch_runemu.py" /usr/bin/runemu.sh "${D}/runemu.sh" "${D}/start_mgbaqol.sh" "${D}/share/main.py"
case $? in
  0)
    chmod +x "${D}/runemu.sh"
    mount --bind "${D}/runemu.sh" /usr/bin/runemu.sh && log "runemu.sh: hook added"
    ;;
  2) log "runemu.sh: already has the hook" ;;
  *) log "runemu.sh: changed too much to patch, the companion won't start (games still run)" ;;
esac

# ES system list: the firmware's current one plus the mgbaqol core for gba.
sed '/<name>gba<\/name>/,/<\/cores>/ s|<core>beetle_gba</core>|<core>beetle_gba</core>\n\t\t\t\t\t<core>mgbaqol</core>|' \
  "${ES_SYS}" >"${D}/es_systems.cfg"
rm -f "${ES_USER}"
cp "${D}/es_systems.cfg" "${ES_USER}"
log "EmulationStation: mgbaqol core added for Game Boy Advance"
log "Done. Restart EmulationStation (systemctl restart essway) the first time."
