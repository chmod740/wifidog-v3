#!/usr/bin/env python3
"""Verify that an IPK upgrade preserves a populated WiFiDog V3 UCI config."""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
CONTAINER = os.environ.get("OPENWRT_CONTAINER", "openwrt-test-v3")
OLD_IPK = Path(os.environ.get(
    "OLD_IPK",
    ROOT / "dist/luci-app-wifidog-v3_1.0.3-1_all.ipk",
))
MAKEFILE = (ROOT / "luci-app-wifidog-v3/Makefile").read_text()
VERSION = re.search(r"^PKG_VERSION:=(.+)$", MAKEFILE, re.MULTILINE).group(1)
RELEASE = re.search(r"^PKG_RELEASE:=(.+)$", MAKEFILE, re.MULTILINE).group(1)
NEW_IPK = Path(os.environ.get(
    "NEW_IPK",
    ROOT / f"dist/luci-app-wifidog-v3_{VERSION}-{RELEASE}_all.ipk",
))


def run(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, timeout=30, check=check)


def dsh(script: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["docker", "exec", CONTAINER, "sh", "-c", script], check=check)


def require(condition: bool, message: str, detail: str = "") -> None:
    if condition:
        print(f"[PASS] {message}")
        return
    print(f"[FAIL] {message} {detail}".rstrip())
    raise RuntimeError(message)


def main() -> int:
    require(OLD_IPK.is_file(), "Old release IPK is available", str(OLD_IPK))
    require(NEW_IPK.is_file(), "New release IPK is available", str(NEW_IPK))
    run(["docker", "cp", str(OLD_IPK), f"{CONTAINER}:/tmp/wifidog-old.ipk"])
    run(["docker", "cp", str(NEW_IPK), f"{CONTAINER}:/tmp/wifidog-new.ipk"])

    dsh("""
set -e
opkg remove luci-app-wifidog-v3 >/dev/null 2>&1 || true
rm -f /etc/config/wifidog_v3 /etc/config/wifidog_v3-opkg /etc/config/wifidog_v3.apk-new
opkg install /tmp/wifidog-old.ipk >/tmp/wifidog-old-install.log
uci -q set wifidog_v3.settings.enabled=1
uci -q set wifidog_v3.settings.portal_theme=dark
uci -q set wifidog_v3.settings.portal_title='升级保留标题'
uci -q set wifidog_v3.settings.radius_secret='upgrade-secret'
uci -q set wifidog_v3.upgrade_device=device
uci -q set wifidog_v3.upgrade_device.mac=AA:BB:CC:DD:EE:42
uci -q set wifidog_v3.upgrade_device.ip=10.88.0.42
uci -q set wifidog_v3.upgrade_device.type=whitelist
uci -q set wifidog_v3.upgrade_device.note='升级保留备注'
uci -q set wifidog_v3.upgrade_code=authcode
uci -q set wifidog_v3.upgrade_code.code=KEEP104
uci -q set wifidog_v3.upgrade_code.max_uses=7
uci -q set wifidog_v3.upgrade_code.used_count=2
uci -q set wifidog_v3.upgrade_code.expiry_days=90
uci -q set wifidog_v3.upgrade_code.auth_minutes=45
uci -q set wifidog_v3.upgrade_code.created_date=2026-07-10
uci -q set wifidog_v3.upgrade_code.enabled=1
uci -q commit wifidog_v3
opkg install /tmp/wifidog-new.ipk >/tmp/wifidog-new-install.log
""")

    values = dsh("""
printf '%s\n' \
  "$(uci -q get wifidog_v3.settings.enabled)" \
  "$(uci -q get wifidog_v3.settings.portal_theme)" \
  "$(uci -q get wifidog_v3.settings.portal_title)" \
  "$(uci -q get wifidog_v3.settings.radius_secret)" \
  "$(uci -q get wifidog_v3.upgrade_device.type)" \
  "$(uci -q get wifidog_v3.upgrade_device.note)" \
  "$(uci -q get wifidog_v3.upgrade_code.code)" \
  "$(uci -q get wifidog_v3.upgrade_code.used_count)" \
  "$(uci -q get wifidog_v3.upgrade_code.auth_minutes)"
""").stdout.splitlines()
    require(values == [
        "1", "dark", "升级保留标题", "upgrade-secret", "whitelist",
        "升级保留备注", "KEEP104", "2", "45",
    ], "Settings, secrets, lists, notes and auth codes survive upgrade", repr(values))

    installed = dsh("opkg list-installed | sed -n 's/^luci-app-wifidog-v3 - //p'").stdout.strip()
    require(installed == f"{VERSION}-{RELEASE}", "New IPK version is installed", installed)
    conffiles = dsh("cat /usr/lib/opkg/info/luci-app-wifidog-v3.conffiles").stdout.strip()
    require(conffiles == "/etc/config/wifidog_v3", "Installed package records protected config", conffiles)
    require(dsh("test ! -e /etc/config/wifidog_v3-opkg", check=False).returncode == 0,
            "Temporary opkg config copy is cleaned")
    require(dsh("test ! -e /etc/config/wifidog_v3.apk-new", check=False).returncode == 0,
            "Temporary apk config copy is cleaned")
    require(dsh("test -s /var/run/wifidog_v3_portal.pid && nft list table inet wifidog_v3 >/dev/null", check=False).returncode == 0,
            "Enabled service resumes after upgrade")
    dsh("rm -f /tmp/wifidog-old.ipk /tmp/wifidog-new.ipk")
    print("\nIPK_UPGRADE_OK")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        if isinstance(exc, subprocess.CalledProcessError):
            print(exc.stdout)
            print(exc.stderr, file=sys.stderr)
        sys.exit(1)
