#!/usr/bin/env python3
"""
RTSagents command wrapper: run commands and emit NDJSON events for the viewer.

Intended pipeline (auto-sync):
  1) python3 ws_server.py --tail events.ndjson
  2) Open index.html, click "WS: ON"
  3) Run commands via this wrapper, e.g.:
       python3 rtswrap.py --log events.ndjson -- npm test

Notes:
  - stdlib only (no pip).
  - Each wrapper invocation appends 2 events: start (ok=null) and end (ok=true/false).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from typing import Any, Dict, Optional


def _now_ms() -> int:
    return int(time.time() * 1000)


def _guess_action(argv: list[str]) -> str:
    s = " ".join(argv).lower()
    if any(
        x in s
        for x in ("pytest", "py.test", "unittest", "nose", "go test", "cargo test")
    ):
        return "test"
    if any(
        x in s
        for x in ("npm test", "pnpm test", "yarn test", "bun test", "vitest", "jest")
    ):
        return "test"
    if any(x in s for x in ("ruff", "eslint", "flake8", "mypy", "pyright")):
        return "test"
    return "run"


def _state_path(log_path: str) -> str:
    return log_path + ".rtswrap_state.json"


def _load_state(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        if isinstance(obj, dict):
            return obj
    except FileNotFoundError:
        return {}
    except Exception:
        return {}
    return {}


def _save_state(path: str, state: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
    os.replace(tmp, path)


def _append_event(path: str, event: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()


def run_once(log_path: str, agent: str, cmd: list[str], reset: bool) -> int:
    if not cmd:
        raise SystemExit("command is required after --")

    action = _guess_action(cmd)
    sp = _state_path(log_path)
    st = {} if reset else _load_state(sp)
    wall0 = int(st.get("wall0_ms") or 0)
    sim0 = int(st.get("t0_ms") or 0)
    last_t = int(st.get("last_t_ms") or 0)
    wall_now = _now_ms()
    if wall0 <= 0 or reset:
        wall0 = wall_now
        sim0 = 0
        last_t = 0

    # Map wall time -> sim time (ms) so the viewer gets small timestamps per session.
    base_t = sim0 + (wall_now - wall0)
    if base_t <= last_t:
        base_t = last_t + 1

    start_evt: Dict[str, Any] = {
        "t": base_t,
        "agent": agent,
        "action": action,
        "detail": " ".join(cmd),
        "ok": None,
    }
    _append_event(log_path, start_evt)

    cmd_wall0 = _now_ms()
    try:
        p = subprocess.run(cmd)
        rc = int(p.returncode)
    except FileNotFoundError:
        rc = 127
    except KeyboardInterrupt:
        rc = 130
    except Exception:
        rc = 1
    cmd_wall1 = _now_ms()

    dur = max(0, cmd_wall1 - cmd_wall0)
    end_evt: Dict[str, Any] = {
        "t": base_t + dur,
        "agent": agent,
        "action": action,
        "detail": " ".join(cmd),
        "ok": rc == 0,
    }
    if action == "test":
        end_evt["tests"] = 1
    _append_event(log_path, end_evt)

    _save_state(sp, {"wall0_ms": wall0, "t0_ms": sim0, "last_t_ms": int(end_evt["t"])})
    return rc


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="rtswrap.py", add_help=True)
    p.add_argument(
        "--log",
        required=True,
        help="NDJSON file to append events to (tail this in ws_server.py)",
    )
    p.add_argument(
        "--agent",
        default=os.environ.get("USER") or "you",
        help="agent id to show as unit name",
    )
    p.add_argument(
        "--reset",
        action="store_true",
        help="Reset local timebase state for this log (starts timeline near 0)",
    )
    p.add_argument("--", dest="_dashdash", action="store_true", help=argparse.SUPPRESS)
    p.add_argument(
        "cmd", nargs=argparse.REMAINDER, help="command to run (put after --)"
    )
    args = p.parse_args(argv)

    cmd = list(args.cmd)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    return run_once(args.log, str(args.agent), cmd, bool(args.reset))


if __name__ == "__main__":
    raise SystemExit(main())
