"""Launch the real desktop entry twice with a hard timeout. Writes pet-launch.log."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path


def run_probe(entry: Path, skin: str) -> str:
    chunks = [f"=== probe {skin} ===\n"]
    proc = subprocess.Popen(
        [str(entry), "--probe", "--probe-skin", skin],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    try:
        out, _ = proc.communicate(timeout=8)
        chunks.append(out or "")
        chunks.append(f"run_exit={proc.returncode}\n")
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            proc.kill()
        leftover = ""
        try:
            leftover, _ = proc.communicate(timeout=1)
        except Exception:
            pass
        chunks.append(leftover or "")
        chunks.append("LAUNCH_ENV_FAIL=outer_timeout\n")
        chunks.append("run_exit=124\n")
    return "".join(chunks)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    scratch = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    entry = root / "bin" / "dsh-desk-pet"
    src = (root / "src" / "dsh_desk_pet" / "app.py").read_text(encoding="utf-8")
    body = []
    body.append(run_probe(entry, "threadcore"))
    body.append(run_probe(entry, "jellyfish"))
    body.append("=== static window setup ===\n")
    body.append(f"HAS_TOPMOST={int('-topmost' in src)}\n")
    body.append(f"HAS_OVERRIDEREDIRECT={int('overrideredirect(True)' in src)}\n")
    body.append(f"HAS_DRAG={int('_on_drag' in src)}\n")
    body.append(f"HAS_DEFAULT_WHALE={int('DEFAULT_SKIN_ID' in src)}\n")
    body.append(f"ENTRY_EXISTS={int(entry.is_file())}\n")
    log = scratch / "pet-launch.log"
    log.write_text("".join(body), encoding="utf-8")
    sys.stdout.write(log.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
