# Copyright (c) 2021 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import errno
import socket

from typing import (
    Tuple,
)


class _Socket:

    def __init__(
            self,
            sock: socket,
    ):
        self.sock = sock
        self._alive = True

    def __enter__(self):
        self.sock.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        if self._alive:
            self.sock.shutdown(socket.SHUT_RDWR)
            self.sock.close()
            self._alive = False

    def send(
            self,
            data: bytes,
    ):
        b_data = bytearray(data)
        offset = 0
        while offset < len(b_data):
            offset += self.sock.send(b_data[offset:])

    def recv(
            self,
            bufsize: int = 1024,
    ):
        try:
            return self.sock.recv(bufsize)
        except socket.error as e:
            if e.errno not in [errno.ESHUTDOWN, errno.ECONNRESET]:
                raise
            self.close()
            return b''


class SocketServer(_Socket):

    def __init__(
            self,
            host: str,
            port: int,
            max_clients: int = 1,
    ):
        super().__init__(socket.socket(socket.AF_INET, socket.SOCK_STREAM))
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((host, port))
        self.sock.listen(max_clients)

    def accept(self) -> 'SocketClient':
        conn, addr = self.sock.accept()
        return SocketClient(conn, addr)


class SocketClient(_Socket):

    def __init__(
            self,
            sock: socket.socket,
            addr: Tuple[str, int],
    ):
        super().__init__(sock)
        self.hostname, self.port = addr
