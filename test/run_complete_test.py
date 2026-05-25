#!/usr/bin/env python3
"""Compatibility wrapper for the current OpenWrt 23.05 container E2E suite."""

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "test" / "e2e_openwrt23_container.py"

if __name__ == "__main__":
    sys.exit(subprocess.call([sys.executable, str(SCRIPT)], cwd=str(ROOT)))
