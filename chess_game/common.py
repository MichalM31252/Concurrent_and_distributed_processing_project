from __future__ import annotations
import json
import struct
import socket
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional

HEADER_SIZE = 4
ENCODING = 'utf-8'

class ConnectionClosed(Exception):
    pass


def send_message(sock: socket.socket, payload: Dict[str, Any]) -> None:
    data = json.dumps(payload).encode(ENCODING)
    sock.sendall(struct.pack('!I', len(data)) + data)


def recv_exact(sock: socket.socket, n: int) -> bytes:
    chunks = []
    remaining = n
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionClosed('Socket closed while reading data.')
        chunks.append(chunk)
        remaining -= len(chunk)
    return b''.join(chunks)


def recv_message(sock: socket.socket) -> Dict[str, Any]:
    header = recv_exact(sock, HEADER_SIZE)
    size = struct.unpack('!I', header)[0]
    body = recv_exact(sock, size)
    return json.loads(body.decode(ENCODING))


@dataclass
class MoveMessage:
    from_pos: str
    to_pos: str
    promotion: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {'type': 'move', **asdict(self)}