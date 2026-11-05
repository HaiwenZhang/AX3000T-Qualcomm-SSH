#!/bin/sh
# /etc/crontabs is bind-mounted from persistent /data on RD03v2 2.0.28.
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
MARKER=/tmp/rd03v2-ssh-ready
SCRIPT=/etc/init.d/dropbear

[ "$(id -u)" = 0 ] || exit 1
if [ -f "$MARKER" ] && pidof dropbear >/dev/null 2>&1; then
    exit 0
fi

if [ "$(nvram get ssh_en)" != 1 ]; then
    nvram set ssh_en=1 || exit 2
    nvram commit || exit 3
fi

if grep -q '"release"' "$SCRIPT"; then
    sed -i 's/"release"/"ssh_enabled"/g' "$SCRIPT" || exit 4
fi

"$SCRIPT" enable || exit 5
"$SCRIPT" restart || exit 6
for attempt in 1 2 3 4 5 6 7 8 9 10; do
    if pidof dropbear >/dev/null 2>&1; then
        touch "$MARKER"
        exit 0
    fi
    sleep 1
done
exit 7
