#!/bin/sh
# Builds the test install and installs it on the console over SSH, plus the dev probes.
set -e
cd "$(dirname "$0")/.."
sh tools/build.sh >/dev/null
KEY="$HOME/.ssh/id_ed25519_rocknix"
HOST=root@RK3566
SSH="ssh -i ${KEY} -o BatchMode=yes ${HOST}"
${SSH} 'mkdir -p /storage/mgbaqol-dev /storage/mgbaqol-probe'
scp -i "${KEY}" -o BatchMode=yes -q -r build/mgbaqol-dev/* "${HOST}:/storage/mgbaqol-dev/"
scp -i "${KEY}" -o BatchMode=yes -q tools/probe/* "${HOST}:/storage/mgbaqol-probe/"
${SSH} 'sh /storage/mgbaqol-dev/install.sh'
