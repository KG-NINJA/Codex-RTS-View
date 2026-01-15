#!/usr/bin/env python3
"""
RTSagents end-to-end sanity checker (stdlib only).

Checks:
  - sessions dir exists and contains rollout .jsonl
  - events log path is writable
  - optional: WS port reachable (TCP)
  - optional: events log is growing
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import time
from pathlib import Path
from typing import Optional, Tuple


def find_latest_jsonl(root: Path) -> Optional[Path]:
    latest: Optional[Tuple[float, Path]] = None
    if not root.exists() or not root.is_dir():
        return None
    for r, _ds, files in os.walk(str(root)):
        for fn in files:
            if not fn.endswith(".jsonl"):
                continue
            p = Path(r) / fn
            try:
                st = p.stat()
            except OSError:
                continue
            key = (st.st_mtime, p)
            if latest is None or key[0] > latest[0]:
                latest = key
    return latest[1] if latest else None


def tcp_check(host: str, port: int, timeout_s: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="doctor.py")
    p.add_argument("--sessions", default=str(Path.home() / ".codex" / "sessions"))
    p.add_argument("--events", default=str(Path.cwd() / "events.ndjson"))
    p.add_argument("--ws-host", default="127.0.0.1")
    p.add_argument("--ws-port", type=int, default=8765)
    p.add_argument("--check-ws", action="store_true")
    p.add_argument("--check-growth", action="store_true", help="Watch events file size for ~2s")
    args = p.parse_args(argv)

    sessions = Path(args.sessions)
    events = Path(args.events)

    print("[doctor] sessions:", sessions)
    latest = find_latest_jsonl(sessions)
    if not latest:
        print("[doctor] FAIL: no .jsonl found under sessions", file=sys.stderr)
    else:
        print("[doctor] OK: latest session:", latest)

    print("[doctor] events:", events)
    try:
        events.parent.mkdir(parents=True, exist_ok=True)
        with events.open("a", encoding="utf-8"):
            pass
        print("[doctor] OK: events path writable")
    except OSError as e:
        print(f"[doctor] FAIL: events path not writable: {e}", file=sys.stderr)

    if args.check_ws:
        ok = tcp_check(args.ws_host, args.ws_port, timeout_s=0.5)
        print(f"[doctor] ws tcp {args.ws_host}:{args.ws_port}:", "OK" if ok else "FAIL")

    if args.check_growth:
        try:
            s0 = events.stat().st_size if events.exists() else 0
        except OSError:
            s0 = 0
        time.sleep(2.0)
        try:
            s1 = events.stat().st_size if events.exists() else 0
        except OSError:
            s1 = s0
        print(f"[doctor] events growth:", f"{s0} -> {s1} bytes", "(OK)" if s1 > s0 else "(NO CHANGE)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

