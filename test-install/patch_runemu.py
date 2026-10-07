#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Writes a copy of ROCKNIX's runemu.sh with the mgba-qol hook added.

  patch_runemu.py SRC DST START_SCRIPT MAIN_PY

Exit codes: 0 written, 1 anchors not found (runemu.sh changed too much),
2 SRC already has the hook (firmware built with mgba-qol).
"""

import sys

# The RetroArch branch, right after setsettings.sh has written the append config.
AFTER_SETTINGS = '      RUNTHIS=$(echo ${RUNTHIS} | sed "s|--config|${EXTRAOPTS} --config|")\n    fi\n'
# Right after the emulator exits.
AFTER_RUN = "        eval ${RUNTHIS} &>>${OUTPUT_LOG}\n        ret_error=$?\n"

HOOK_START = '''
    ### mgba-qol: live companion on the second screen, only for this core.
    ### It reads game RAM through RetroArch's network commands.
    if [ "${CORE}" = "mgbaqol" ]; then
      echo 'network_cmd_enable = "true"' >> "${RETROARCH_APPEND_CONFIG}"
      echo 'network_cmd_port = "55355"' >> "${RETROARCH_APPEND_CONFIG}"
      %s "${ROMNAME}" &
    fi
'''
HOOK_STOP = '''        # The companion also exits on its own a few seconds after RetroArch.
        [ "${CORE}" = "mgbaqol" ] && pkill -f %s
'''


def main():
    src, dst, start_script, main_py = sys.argv[1:5]
    with open(src) as f:
        s = f.read()
    if '"${CORE}" = "mgbaqol"' in s:
        return 2
    if s.count(AFTER_SETTINGS) != 1 or s.count(AFTER_RUN) != 1:
        return 1
    s = s.replace(AFTER_SETTINGS, AFTER_SETTINGS + HOOK_START % start_script)
    s = s.replace(AFTER_RUN, AFTER_RUN + HOOK_STOP % main_py)
    with open(dst, "w") as f:
        f.write(s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
