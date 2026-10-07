#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
# Copyright (C) 2026-present ROCKNIX (https://github.com/ROCKNIX)

# Starts the mgba-qol companion on the second screen. runemu.sh calls this in
# the background for the mgbaqol core; the companion exits with RetroArch.

. /etc/profile

ROM="$1"
LOG=/var/log/mgbaqol.log

if [ "${DEVICE_HAS_DUAL_SCREEN}" != "true" ]; then
  echo "no second screen on ${QUIRK_DEVICE}, companion not started" >"${LOG}"
  exit 0
fi

case "${QUIRK_DEVICE}" in
  *)
    # RG DS: game on DSI-2 (top), companion on DSI-1 (bottom).
    OUTPUT="DSI-1"
    ;;
esac

# RetroArch is started right after us; wait for it so --ra-pid is right.
RA_PID=""
for _ in $(seq 1 100); do
  RA_PID=$(pidof retroarch | awk '{print $1}')
  [ -n "${RA_PID}" ] && break
  sleep 0.1
done

exec python3 /usr/share/mgbaqol/main.py --rom "${ROM}" --ra-pid "${RA_PID:-0}" --output "${OUTPUT}" >"${LOG}" 2>&1
