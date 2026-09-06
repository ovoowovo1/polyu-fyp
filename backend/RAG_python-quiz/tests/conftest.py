"""Offline-only unit suite: accidental network/model requests must fail before transport."""
import socket
from unittest.mock import patch

import httpx
import requests


def deny_network(*args, **kwargs):
    raise AssertionError("External network is disabled in unit tests; mock the provider boundary")


async def deny_async_network(*args, **kwargs):
    deny_network()


_connect = socket.socket.connect
_connect_ex = socket.socket.connect_ex


def guarded_connect(sock, address):
    if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"):
        return _connect(sock, address)
    deny_network()


def guarded_connect_ex(sock, address):
    if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"):
        return _connect_ex(sock, address)
    deny_network()


_guards = []


def pytest_sessionstart(session):
    # Installed before collection, including imports that might initialize clients.
    for target, name, replacement in (
        (socket.socket, "connect", guarded_connect),
        (socket.socket, "connect_ex", guarded_connect_ex),
        (requests.sessions.Session, "request", deny_network),
        (httpx.HTTPTransport, "handle_request", deny_network),
        (httpx.AsyncHTTPTransport, "handle_async_request", deny_async_network),
    ):
        guard = patch.object(target, name, replacement)
        guard.start()
        _guards.append(guard)


def pytest_sessionfinish(session, exitstatus):
    for guard in reversed(_guards):
        guard.stop()
    _guards.clear()
