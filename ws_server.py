#!/usr/bin/env python3
"""
Minimal stdlib-only WebSocket server for RTSagents/index.html.

Purpose
  - Accept ws://localhost:8765 connections from the viewer
  - Broadcast incoming text frames (NDJSON lines) to all connected clients
  - Optionally broadcast lines read from stdin and/or a tailed file

Why stdlib-only?
  - No pip / no external libs required.

Protocol support
  - RFC 6455 (subset): text frames, ping/pong, close
  - Clients must mask frames (browsers do); server sends unmasked frames.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import dataclasses
import hashlib
import os
import sys
import time
from typing import Dict, Optional, Set, Tuple


WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


@dataclasses.dataclass(frozen=True)
class Client:
    writer: asyncio.StreamWriter
    addr: Tuple[str, int]


class Hub:
    def __init__(self, verbose: bool) -> None:
        self._clients: Set[Client] = set()
        self._lock = asyncio.Lock()
        self._verbose = verbose

    async def add(self, client: Client) -> None:
        async with self._lock:
            self._clients.add(client)

    async def remove(self, client: Client) -> None:
        async with self._lock:
            self._clients.discard(client)

    async def broadcast_text(self, text: str) -> None:
        data = encode_ws_text(text)
        dead: Set[Client] = set()
        async with self._lock:
            if self._verbose:
                print(
                    f"[ws_server] broadcast {len(text)} chars to {len(self._clients)} clients",
                    flush=True,
                )
            for c in self._clients:
                try:
                    c.writer.write(data)
                    await c.writer.drain()
                except Exception:
                    dead.add(c)
            for c in dead:
                self._clients.discard(c)
                try:
                    c.writer.close()
                except Exception:
                    pass

    async def count(self) -> int:
        async with self._lock:
            return len(self._clients)


def parse_http_headers(request: bytes) -> Dict[str, str]:
    try:
        text = request.decode("utf-8", errors="replace")
    except Exception:
        text = ""
    lines = text.split("\r\n")
    headers: Dict[str, str] = {}
    for line in lines[1:]:
        if not line:
            break
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        headers[k.strip().lower()] = v.strip()
    return headers


def ws_accept_key(sec_ws_key: str) -> str:
    sha1 = hashlib.sha1((sec_ws_key + WS_GUID).encode("utf-8")).digest()
    return base64.b64encode(sha1).decode("ascii")


def encode_ws_text(text: str) -> bytes:
    payload = text.encode("utf-8")
    fin_opcode = 0x80 | 0x1  # FIN + text
    n = len(payload)
    if n <= 125:
        header = bytes([fin_opcode, n])
    elif n <= 65535:
        header = bytes([fin_opcode, 126]) + n.to_bytes(2, "big")
    else:
        header = bytes([fin_opcode, 127]) + n.to_bytes(8, "big")
    return header + payload


def encode_ws_control(opcode: int, payload: bytes = b"") -> bytes:
    fin_opcode = 0x80 | (opcode & 0x0F)
    n = len(payload)
    if n > 125:
        payload = payload[:125]
        n = len(payload)
    return bytes([fin_opcode, n]) + payload


async def read_until(reader: asyncio.StreamReader, marker: bytes, limit: int) -> bytes:
    buf = bytearray()
    while True:
        chunk = await reader.read(1024)
        if not chunk:
            break
        buf += chunk
        if marker in buf:
            break
        if len(buf) > limit:
            break
    return bytes(buf)


async def ws_read_frame(reader: asyncio.StreamReader) -> Optional[Tuple[int, bytes]]:
    # Returns (opcode, payload) or None on EOF.
    b1 = await reader.readexactly(1) if not reader.at_eof() else b""
    if not b1:
        return None
    b2 = await reader.readexactly(1)
    fin = (b1[0] & 0x80) != 0
    opcode = b1[0] & 0x0F
    masked = (b2[0] & 0x80) != 0
    length = b2[0] & 0x7F

    if length == 126:
        length = int.from_bytes(await reader.readexactly(2), "big")
    elif length == 127:
        length = int.from_bytes(await reader.readexactly(8), "big")

    mask = await reader.readexactly(4) if masked else None
    payload = await reader.readexactly(length) if length else b""
    if masked and mask is not None and payload:
        payload = bytes(b ^ mask[i & 3] for i, b in enumerate(payload))

    # We ignore fragmentation (FIN must be set for our usage).
    if not fin and opcode in (0x1, 0x2, 0x0):
        # Best-effort: treat as protocol error and drop.
        return (0x8, b"")
    return (opcode, payload)


async def handle_client(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter, hub: Hub
) -> None:
    peer = writer.get_extra_info("peername")
    addr = ("?", 0)
    if isinstance(peer, tuple) and len(peer) >= 2:
        addr = (str(peer[0]), int(peer[1]))
    client = Client(writer=writer, addr=addr)

    try:
        req = await read_until(reader, b"\r\n\r\n", limit=64 * 1024)
        if b"\r\n\r\n" not in req:
            writer.write(b"HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n")
            await writer.drain()
            return

        headers = parse_http_headers(req)
        if headers.get("upgrade", "").lower() != "websocket":
            writer.write(b"HTTP/1.1 426 Upgrade Required\r\nConnection: close\r\n\r\n")
            await writer.drain()
            return

        key = headers.get("sec-websocket-key")
        if not key:
            writer.write(b"HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n")
            await writer.drain()
            return

        accept = ws_accept_key(key)
        resp = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n"
            "\r\n"
        ).encode("utf-8")
        writer.write(resp)
        await writer.drain()

        await hub.add(client)
        await hub.broadcast_text(
            f'{{"t":0,"agent":"ws","action":"log","detail":"client connected {addr[0]}:{addr[1]}","ok":true}}'
        )

        while True:
            try:
                frame = await ws_read_frame(reader)
            except asyncio.IncompleteReadError:
                frame = None
            if frame is None:
                break

            opcode, payload = frame

            if opcode == 0x8:  # close
                writer.write(encode_ws_control(0x8, b""))
                await writer.drain()
                break
            if opcode == 0x9:  # ping
                writer.write(encode_ws_control(0xA, payload[:125]))
                await writer.drain()
                continue
            if opcode == 0xA:  # pong
                continue
            if opcode != 0x1:  # not text
                continue

            try:
                msg = payload.decode("utf-8", errors="replace")
            except Exception:
                continue

            # Allow multi-line payloads; viewer expects NDJSON (1 event per line).
            for line in msg.splitlines():
                s = line.strip()
                if not s:
                    continue
                await hub.broadcast_text(s)
    finally:
        await hub.remove(client)
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def stdin_broadcaster(hub: Hub) -> None:
    loop = asyncio.get_running_loop()

    def _readline_blocking() -> str:
        return sys.stdin.readline()

    while True:
        line = await loop.run_in_executor(None, _readline_blocking)
        if not line:
            return
        s = line.strip("\r\n")
        if not s:
            continue
        await hub.broadcast_text(s)


async def tail_broadcaster(
    hub: Hub, path: str, poll_ms: int, from_start: bool, verbose: bool
) -> None:
    # Default behavior is "tail -f": start at EOF so we don't replay old sessions.
    # This keeps viewer timelines small and avoids scheduling events far in the future.
    if from_start:
        last_pos = 0
    else:
        try:
            with open(path, "rb") as f:
                f.seek(0, os.SEEK_END)
                last_pos = f.tell()
        except Exception:
            last_pos = 0
    while True:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(last_pos, os.SEEK_SET)
                chunk = f.read()
                last_pos = f.tell()
        except FileNotFoundError:
            chunk = ""
        except Exception:
            chunk = ""

        if chunk:
            n_sent = 0
            for line in chunk.splitlines():
                s = line.strip()
                if not s:
                    continue
                await hub.broadcast_text(s)
                n_sent += 1
            if verbose and n_sent:
                print(f"[ws_server] tail sent {n_sent} lines", flush=True)
        await asyncio.sleep(max(0.05, poll_ms / 1000))


async def run_server(
    host: str,
    port: int,
    use_stdin: bool,
    tail: Optional[str],
    tail_poll_ms: int,
    tail_from_start: bool,
    verbose: bool,
) -> None:
    hub = Hub(verbose=verbose)
    server = await asyncio.start_server(
        lambda r, w: handle_client(r, w, hub), host=host, port=port
    )
    addrs = ", ".join(str(sock.getsockname()) for sock in server.sockets or [])
    print(f"[ws_server] listening on {addrs}", flush=True)

    tasks = []
    if use_stdin:
        tasks.append(asyncio.create_task(stdin_broadcaster(hub)))
        print(
            "[ws_server] stdin broadcast enabled (NDJSON 1 line per event)", flush=True
        )
    if tail:
        tasks.append(
            asyncio.create_task(
                tail_broadcaster(hub, tail, tail_poll_ms, tail_from_start, verbose)
            )
        )
        mode = "from start" if tail_from_start else "from EOF"
        print(f"[ws_server] tail broadcast enabled ({mode}): {tail}", flush=True)

    async with server:
        await server.serve_forever()
    for t in tasks:
        t.cancel()


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="ws_server.py",
        description="Stdlib WebSocket broadcast server for RTSagents viewer",
    )
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument(
        "--stdin",
        action="store_true",
        help="Broadcast each line read from stdin to all clients",
    )
    p.add_argument(
        "--tail",
        default=None,
        help="Tail a file and broadcast appended lines (best-effort)",
    )
    p.add_argument(
        "--tail-poll-ms", type=int, default=120, help="Tail poll interval in ms"
    )
    p.add_argument(
        "--verbose", action="store_true", help="Print per-broadcast debug logs"
    )
    p.add_argument(
        "--tail-from-start",
        action="store_true",
        help="Replay the whole file from the beginning (default is tail -f behavior: start at EOF)",
    )
    args = p.parse_args(argv)

    try:
        asyncio.run(
            run_server(
                args.host,
                args.port,
                args.stdin,
                args.tail,
                args.tail_poll_ms,
                args.tail_from_start,
                args.verbose,
            )
        )
    except KeyboardInterrupt:
        return 0
    except OSError as e:
        # Common case on Windows: WinError 10048 (address already in use).
        msg = str(e)
        winerr = getattr(e, "winerror", None)
        if (
            winerr == 10048
            or e.errno in (98, 10048)
            or "address already in use" in msg.lower()
        ):
            print(
                f"[ws_server] ERROR: cannot bind {args.host}:{args.port} (already in use)",
                file=sys.stderr,
                flush=True,
            )
            print(
                "[ws_server] Hint: stop the existing server or choose a different --port.",
                file=sys.stderr,
                flush=True,
            )
            return 2
        print(f"[ws_server] ERROR: {e}", file=sys.stderr, flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
