#!/usr/bin/env bash
# Apply the reviewed servo settings, then reboot to prove the boot path.
#
# Run on the Pi from the repository root:
#   bash deploy/apply-and-reboot.sh
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$REPO/.venv/bin/python"
cd "$REPO"

echo "== 1. Stop anything already driving the bus =="
sudo systemctl stop mio-head.service 2>/dev/null || true
pkill -f "mio_core_services.firmware" 2>/dev/null || true
sleep 3

echo
echo "== 2. Update =="
git pull --ff-only

echo
echo "== 3. Restore the reviewed register baseline =="
# P32 / I0 / D32, punch 16, dead zone 1. The earlier lowered punch and widened
# dead zone sat inside the gear train's lost motion and made hunting worse.
for id in 1 2; do
  "$PY" -m mio_core_services.firmware.tune_servo --id "$id" --baseline
done

echo
echo "== 4. Write and verify the hard travel limits =="
"$PY" -m mio_core_services.firmware.apply_limits
"$PY" -m mio_core_services.firmware.apply_limits --verify

echo
echo "== 5. Install and enable the boot service =="
sudo cp deploy/mio-head.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable mio-head.service

echo
echo "== 6. Rebooting =="
echo "On boot the head centres slowly, sweeps its full range, then idles."
echo "Watch it with:  journalctl -u mio-head.service -f"
sleep 3
sudo reboot
