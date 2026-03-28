"""
Allow running the daemon as:  python3 -m g510
"""
import sys
import os

# Resolve the daemon script relative to this package
from pathlib import Path
daemon_script = Path(__file__).parent.parent / "g510-daemon.py"

if daemon_script.exists():
    # Exec the daemon script in this interpreter
    exec(compile(daemon_script.read_text(), str(daemon_script), "exec"))
else:
    print(f"Error: daemon script not found at {daemon_script}", file=sys.stderr)
    sys.exit(1)
