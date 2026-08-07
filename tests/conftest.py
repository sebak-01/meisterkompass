"""
Test-wide network isolation.

Most tests parse fixture HTML and must never touch a chamber website: doing so
makes them slow (106s vs 12s for the suite) and couples them to 60 third-party
sites being up. Sockets are therefore blocked by default, so a newly written
test cannot silently start hitting the network.

Tests that deliberately fetch live pages are marked ``@pytest.mark.network``.
They are deselected by default and run as a scheduled canary — they are the
only thing that notices a chamber quietly changing its HTML, so they are kept
rather than deleted. Run them with ``pytest -m network``.
"""

import re
import socket

import pytest

_ALLOWED = {"127.0.0.1", "::1", "localhost"}
_real_socket_connect = socket.socket.connect
_real_create_connection = socket.create_connection


class NetworkAccessBlocked(RuntimeError):
    pass


def _host_of(address):
    if isinstance(address, tuple) and address:
        return address[0]
    return address


def _blocked_connect(self, address, *args, **kwargs):
    if _host_of(address) in _ALLOWED:
        return _real_socket_connect(self, address, *args, **kwargs)
    raise NetworkAccessBlocked(
        f"blocked network connection to {_host_of(address)!r}. Mock the fetch, "
        f"or mark the test @pytest.mark.network if it must hit a live site."
    )


def _blocked_create_connection(address, *args, **kwargs):
    if _host_of(address) in _ALLOWED:
        return _real_create_connection(address, *args, **kwargs)
    raise NetworkAccessBlocked(
        f"blocked network connection to {_host_of(address)!r}. Mock the fetch, "
        f"or mark the test @pytest.mark.network if it must hit a live site."
    )


def pytest_collection_modifyitems(config, items):
    # Only a marker expression that actually mentions `network` is taken as
    # intent to run them. Bailing out on any -m at all would silently unblock
    # live HTTP for an unrelated selection such as -m "not slow".
    if re.search(r"\bnetwork\b", config.getoption("-m") or ""):
        return
    skip = pytest.mark.skip(reason="live-network test; run with -m network")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _block_network(request):
    if "network" in request.keywords:
        yield
        return
    socket.socket.connect = _blocked_connect
    socket.create_connection = _blocked_create_connection
    try:
        yield
    finally:
        socket.socket.connect = _real_socket_connect
        socket.create_connection = _real_create_connection
