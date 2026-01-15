#!/usr/bin/env python3
"""
Codex CLI -> RTSagents bridge (stdlib only).

Watches Codex CLI session JSONL files (typically ~/.codex/sessions/**/rollout-*.jsonl),
extracts user/agent chat messages, and appends them as RTSagents NDJSON events into
an events log file that ws_server.py can tail/broadcast to the viewer.

Typical setup:
  1) python3 ws_server.py --tail events.ndjson
  2) Open index.html and click "WS: ON"
  3) python3 codex_cli_bridge.py --log events.ndjson
  4) Use Codex CLI as usual; chat turns will move units.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Deque, Dict, Iterable, Optional, Tuple


def now_ms() -> int:
    return int(time.time() * 1000)


def clamp_detail(s: str, n: int) -> str:
    t = " ".join(str(s).split())
    return t if len(t) <= n else t[: max(0, n - 1)] + "…"


def guess_action(role: str, text: str) -> str:
    s = text.lower()
    if role == "user":
        return "plan"
    if any(
        k in s
        for k in (
            "pytest",
            "npm test",
            "pnpm test",
            "yarn test",
            "bun test",
            "go test",
            "cargo test",
        )
    ):
        return "test"
    if any(
        k in s
        for k in (
            "apply_patch",
            "diff",
            "patch",
            "edit",
            "fix",
            "update file",
            "add file",
        )
    ):
        return "edit"
    if any(
        k in s
        for k in ("run ", "cmd", "command", "python3 ", "node ", "bash ", "powershell")
    ):
        return "run"
    return "edit"


def iter_rollout_files(sessions_dir: Path) -> Iterable[Path]:
    # pathlib.Path.glob("**/*.jsonl") can be flaky on some UNC/WSL-mounted paths on Windows.
    # Use os.walk for maximum compatibility.
    if not sessions_dir.exists() or not sessions_dir.is_dir():
        return []
    for root, _dirs, files in os.walk(str(sessions_dir)):
        for fn in files:
            if fn.endswith(".jsonl"):
                yield Path(root) / fn


def find_latest_rollout(sessions_dir: Path) -> Optional[Path]:
    latest: Optional[Tuple[float, Path]] = None
    for p in iter_rollout_files(sessions_dir):
        try:
            st = p.stat()
        except OSError:
            continue
        key = (st.st_mtime, p)
        if latest is None or key[0] > latest[0]:
            latest = key
    return latest[1] if latest else None


def append_event(log_path: Path, evt: Dict) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(evt, ensure_ascii=False, separators=(",", ":")) + "\n")
        f.flush()


@dataclass
class TailState:
    path: Path
    fp: object


def open_tail(path: Path, from_start: bool) -> TailState:
    f = path.open("r", encoding="utf-8", errors="replace")
    if not from_start:
        f.seek(0, os.SEEK_END)
    return TailState(path=path, fp=f)


def close_tail(ts: TailState) -> None:
    try:
        ts.fp.close()
    except Exception:
        pass


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="codex_cli_bridge.py")
    p.add_argument(
        "--sessions",
        default=str(Path.home() / ".codex" / "sessions"),
        help="Codex sessions dir",
    )
    p.add_argument(
        "--log", required=True, help="RTSagents NDJSON events file to append"
    )
    p.add_argument(
        "--from-start",
        action="store_true",
        help="Replay from start of session file (default: follow new lines only)",
    )
    p.add_argument(
        "--follow-latest",
        action="store_true",
        help="Auto-switch to newest rollout JSONL if Codex starts a new session (recommended)",
    )
    p.add_argument(
        "--poll-ms",
        type=int,
        default=150,
        help="Polling interval for new lines / latest session switch",
    )
    p.add_argument(
        "--max-detail",
        type=int,
        default=260,
        help="Max chars of message to include in event.detail",
    )
    p.add_argument(
        "--verbose", action="store_true", help="Print one line per emitted event"
    )
    args = p.parse_args(argv)

    sessions_dir = Path(args.sessions)
    log_path = Path(args.log)

    latest = find_latest_rollout(sessions_dir)
    if not latest:
        print(
            f"[codex_cli_bridge] no session jsonl found under: {sessions_dir}",
            file=sys.stderr,
        )
        return 2

    tail = open_tail(latest, from_start=bool(args.from_start))
    print(f"[codex_cli_bridge] watching: {tail.path}", flush=True)

    started_wall = now_ms()
    last_emit_t = 0

    # de-dup in case of UI refresh / repeated tail reads
    recent_keys: Deque[str] = deque(maxlen=1024)
    recent_set = set()

    def seen_add(k: str) -> bool:
        if k in recent_set:
            return True
        recent_keys.append(k)
        recent_set.add(k)
        if len(recent_keys) == recent_keys.maxlen:
            # trim set to match deque
            recent_set.clear()
            recent_set.update(recent_keys)
        return False

    try:
        while True:
            line = tail.fp.readline()
            if line:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue

                if obj.get("type") != "event_msg":
                    continue
                payload = obj.get("payload")
                if not isinstance(payload, dict):
                    continue
                ptype = payload.get("type")
                if ptype not in ("user_message", "agent_message"):
                    continue

                msg = payload.get("message")
                if not isinstance(msg, str) or not msg.strip():
                    continue

                role = "user" if ptype == "user_message" else "assistant"
                agent = "codex:user" if role == "user" else "codex:assistant"
                detail = clamp_detail(msg, int(args.max_detail))
                action = guess_action(role, detail)

                # Use bridge wall-clock so events apply immediately even if session file has an old timebase.
                t = now_ms() - started_wall
                if t <= last_emit_t:
                    t = last_emit_t + 1
                last_emit_t = t

                key = f"{ptype}|{detail}"
                if seen_add(key):
                    continue

                append_event(
                    log_path,
                    {
                        "t": int(t),
                        "agent": agent,
                        "action": action,
                        "detail": detail,
                        "ok": True,
                    },
                )
                if args.verbose:
                    print(
                        f"[codex_cli_bridge] emit {agent} {action}: {detail[:60]}",
                        flush=True,
                    )
                continue

            # no new line: maybe switch to latest file
            if args.follow_latest:
                newest = find_latest_rollout(sessions_dir)
                if newest and newest != tail.path:
                    close_tail(tail)
                    tail = open_tail(newest, from_start=bool(args.from_start))
                    print(f"[codex_cli_bridge] switched to: {tail.path}", flush=True)

            time.sleep(max(0.05, int(args.poll_ms) / 1000.0))
    except KeyboardInterrupt:
        return 0
    finally:
        close_tail(tail)


if __name__ == "__main__":
    raise SystemExit(main())
