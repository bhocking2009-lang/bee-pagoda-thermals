#!/usr/bin/env bash
set -euo pipefail

OUT_DIR="$(cd "$(dirname "$0")/.." && pwd)/artifacts"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$OUT_DIR/capability-scan-$STAMP.txt"
mkdir -p "$OUT_DIR"

{
  echo "# Bee Pagoda capability scan"
  echo "timestamp: $(date -Is)"
  echo
  echo "== Host =="
  hostnamectl || true
  echo
  echo "== OS/Kernel =="
  uname -a
  [ -f /etc/os-release ] && cat /etc/os-release
  echo
  echo "== CPU =="
  lscpu | sed -n '1,80p'
  echo
  echo "== GPU PCI =="
  lspci -nn | grep -Ei 'VGA|3D|Display' || true
  echo
  echo "== DMI/BIOS =="
  for f in /sys/devices/virtual/dmi/id/{board_vendor,board_name,board_version,bios_vendor,bios_version,bios_date,product_name,product_version}; do
    [ -r "$f" ] && printf '%s: %s\n' "$(basename "$f")" "$(cat "$f")"
  done
  echo
  echo "== Storage =="
  lsblk -o NAME,SIZE,TYPE,MODEL,SERIAL,MOUNTPOINT
  command -v nvme >/dev/null && { echo; nvme list; } || true
  echo
  echo "== hwmon =="
  ls -la /sys/class/hwmon || true
  for d in /sys/class/hwmon/hwmon*; do
    [ -d "$d" ] || continue
    name=$(cat "$d/name" 2>/dev/null || echo unknown)
    echo "[$(basename "$d")] name=$name"
    ls "$d" | grep -E 'temp[0-9]+_input|fan[0-9]+_input|pwm[0-9]+|pwm[0-9]+_enable' || true
  done
  echo
  echo "== thermal/fan services =="
  systemctl list-units --type=service --state=running | grep -Ei 'thermald|fancontrol|liquid|asus|lenovo|dell|msi|amdgpu' || true
  echo
  echo "== fwupd =="
  if command -v fwupdmgr >/dev/null; then
    fwupdmgr --version || true
    fwupdmgr get-devices || true
    fwupdmgr get-updates || true
  else
    echo "fwupdmgr not installed"
  fi
} | tee "$OUT"

echo
printf 'Wrote %s\n' "$OUT"
