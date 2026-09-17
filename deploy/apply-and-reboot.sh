#!/usr/bin/env bash
# Apply the reviewed servo settings, then reboot to prove the boot path.
#
# Run on the Pi from the repository root:
#   bash deploy/apply-and-reboot.sh
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$REPO/.venv/bin/python"
cd "$REPO"

if ! command -v lk >/dev/null 2>&1; then
  echo "LiveKit CLI is required. Install it with:"
  echo "  sudo apt-get install -y jq"
  echo "  curl -sSL https://get.livekit.io/cli | bash"
  exit 1
fi

echo "== 1. Stop anything already driving the bus, the eyes, WiFi setup, or the conversation mic =="
sudo systemctl stop mio-wifi.service mio-head.service mio-eyes.service mio-conversation.service 2>/dev/null || true
pkill -f "mio_core_services.wifi" 2>/dev/null || true
pkill -f "mio_core_services.firmware" 2>/dev/null || true
pkill -f "mio_core_services.lighting" 2>/dev/null || true
sleep 3

echo
echo "== 2. Update =="
if git rev-parse --abbrev-ref --symbolic-full-name '@{u}' >/dev/null 2>&1; then
  git pull --ff-only
else
  echo "No upstream for $(git branch --show-current); using this tree."
fi

UV_BIN="${UV:-uv}"
if ! command -v "$UV_BIN" >/dev/null 2>&1; then
  UV_BIN="$HOME/.local/bin/uv"
fi
"$UV_BIN" sync
if ! "$PY" -m livekit.agents download-files; then
  echo "download-files did not succeed; continuing so boot units still install."
fi

echo
echo "== 3. Restore the reviewed register baseline =="
# P32 / I0 / D32, punch 16, dead zone 1. The earlier lowered punch and widened
# dead zone sat inside the gear train's lost motion and made hunting worse.
for id in 1 2; do
  "$PY" -m mio_core_services.firmware.tuning.tune_servo --id "$id" --baseline
done

echo
echo "== 4. Write and verify the hard travel limits =="
"$PY" -m mio_core_services.firmware.calibration.apply_limits
"$PY" -m mio_core_services.firmware.calibration.apply_limits --verify

echo
echo "== 5. Install and enable the boot services =="
# Recopy from the repo so a stale installed unit (e.g. the pre-runtime
# firmware.idle_motion path) is overwritten before the reboot.
sudo cp deploy/mio-wifi.service deploy/mio-head.service deploy/mio-eyes.service deploy/mio-conversation.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable mio-wifi.service mio-head.service mio-eyes.service mio-conversation.service
systemctl cat mio-wifi.service mio-head.service mio-eyes.service mio-conversation.service | grep ExecStart

echo
echo "== 6. Rebooting =="
echo "On boot, WiFi setup runs first. If the Pi is already online the head, eyes, and conversation start; if not, the eyes fade until a phone joins Mio-Setup and picks a network."
echo "Watch it with:  journalctl -u mio-wifi.service -u mio-head.service -u mio-eyes.service -u mio-conversation.service -f"
sleep 3
sudo reboot
