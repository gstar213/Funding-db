"""
setup_scheduler.py — Register auto-collection tasks in Windows Task Scheduler.

Creates two scheduled tasks:
  1. FundingDB-OnBoot  : runs `python main.py collect` 2 minutes after every system startup
  2. FundingDB-Every6h : runs `python main.py collect` every 6 hours while the PC is on

Usage (run once, as Administrator for best results):
    python setup_scheduler.py          # install tasks
    python setup_scheduler.py --remove # remove tasks
    python setup_scheduler.py --status # check task status
"""

import subprocess
import sys
import argparse
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

TASK_BOOT = "FundingDB-OnBoot"
TASK_INTERVAL = "FundingDB-Every6h"

# Absolute path to this project
PROJECT_DIR = Path(__file__).resolve().parent
PYTHON = sys.executable  # same python that's running this script
SCRIPT = str(PROJECT_DIR / "main.py")

# ── Helpers ───────────────────────────────────────────────────────────────────

def run(cmd: list[str], check=True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def schtasks(*args) -> subprocess.CompletedProcess:
    return run(["schtasks"] + list(args), check=False)


def task_exists(name: str) -> bool:
    r = schtasks("/Query", "/TN", name, "/FO", "LIST")
    return r.returncode == 0


def delete_task(name: str):
    if task_exists(name):
        r = schtasks("/Delete", "/TN", name, "/F")
        if r.returncode == 0:
            print(f"  ✓ Removed: {name}")
        else:
            print(f"  ✗ Failed to remove {name}: {r.stderr.strip()}")
    else:
        print(f"  · Not found (already removed): {name}")


# ── Actions ───────────────────────────────────────────────────────────────────

def install():
    print(f"\n📦 Installing scheduled tasks...")
    print(f"   Python : {PYTHON}")
    print(f"   Script : {SCRIPT}")
    print(f"   Dir    : {PROJECT_DIR}\n")

    # ── Task 1: On Boot (2-minute delay) ─────────────────────────────────────
    delete_task(TASK_BOOT)  # fresh install
    r = schtasks(
        "/Create", "/TN", TASK_BOOT,
        "/TR", f'"{PYTHON}" -X utf8 "{SCRIPT}" collect',
        "/SC", "ONSTART",           # trigger: system startup
        "/DELAY", "0002:00",        # wait 2 minutes before running
        "/RL", "HIGHEST",           # run with highest available privileges
        "/F",                       # force overwrite
        "/ST", "00:00",
        "/SD", "01/01/2026",
    )
    if r.returncode == 0:
        print(f"  ✓ Created: {TASK_BOOT}  (runs 2 min after every boot)")
    else:
        print(f"  ✗ Failed: {r.stderr.strip()}")

    # ── Task 2: Every 6 Hours ─────────────────────────────────────────────────
    delete_task(TASK_INTERVAL)
    r = schtasks(
        "/Create", "/TN", TASK_INTERVAL,
        "/TR", f'"{PYTHON}" -X utf8 "{SCRIPT}" collect',
        "/SC", "HOURLY",
        "/MO", "6",                 # every 6 hours
        "/RL", "HIGHEST",
        "/F",
        "/ST", "00:00",
        "/SD", "01/01/2026",
    )
    if r.returncode == 0:
        print(f"  ✓ Created: {TASK_INTERVAL}  (runs every 6 hours)")
    else:
        print(f"  ✗ Failed: {r.stderr.strip()}")

    print("\n✅ Done! Open Task Scheduler to verify.")
    print("   Or run: python setup_scheduler.py --status\n")


def remove():
    print("\n🗑️  Removing scheduled tasks...")
    delete_task(TASK_BOOT)
    delete_task(TASK_INTERVAL)
    print("\n✅ Done.\n")


def status():
    print("\n📋 Task Scheduler status:\n")
    for name in [TASK_BOOT, TASK_INTERVAL]:
        r = schtasks("/Query", "/TN", name, "/FO", "LIST", "/V")
        if r.returncode == 0:
            # Print just the key lines
            for line in r.stdout.splitlines():
                if any(k in line for k in ("TaskName", "Status", "Next Run", "Last Run", "Last Result")):
                    print(f"  {line.strip()}")
            print()
        else:
            print(f"  · {name}: NOT FOUND\n")


# ── Entry ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manage FundingDB scheduled tasks")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--remove", action="store_true", help="Remove both tasks")
    group.add_argument("--status", action="store_true", help="Show task status")
    args = parser.parse_args()

    if args.remove:
        remove()
    elif args.status:
        status()
    else:
        install()
