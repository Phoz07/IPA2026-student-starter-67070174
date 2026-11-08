"""Helpers shared by the backend adapters."""

import os
import re
from ipaddress import IPv4Interface, IPv4Network

AUTH_FAILED = "authentication_failed"
CONNECTION_FAILED = "connection_failed"
BACKEND_FAILED = "backend_failed"

_AUTH_NAMES = {
    "AuthenticationError",
    "AuthenticationException",
    "NetmikoAuthenticationException",
}
_CONNECTION_NAMES = {
    "NetmikoTimeoutException",
    "SSHError",
    "SSHException",
    "NoValidConnectionsError",
    "TransportError",
    "SessionCloseError",
    "Timeout",
    "ConnectionError",
}

_INTERFACE_NAME = re.compile(r"[A-Za-z][A-Za-z0-9/.\-]*")
_LOOPBACK_NAME = re.compile(r"Loopback([0-9]+)")


def error_response(result):
    return {"status": "error", "result": result}


def found_response(interface):
    return {"status": "ok", "result": "found", "interface": interface}


def not_found_response():
    return {"status": "ok", "result": "not_found", "interface": None}


def applied_response():
    return {"status": "ok", "result": "applied"}


def classify_exception(exc):
    """Map any transport/runner exception to a backend error code."""
    if isinstance(exc, PermissionError):
        return AUTH_FAILED
    names = {cls.__name__ for cls in type(exc).__mro__}
    if names & _AUTH_NAMES:
        return AUTH_FAILED
    if isinstance(exc, ValueError):
        return BACKEND_FAILED
    if names & _CONNECTION_NAMES or isinstance(exc, OSError):
        return CONNECTION_FAILED
    return BACKEND_FAILED


def error_from_exception(exc):
    return error_response(classify_exception(exc))


def router_credentials():
    return os.environ.get("ROUTER_USER", ""), os.environ.get("ROUTER_PASS", "")


def validate_interface_name(name):
    """Reject names that could inject extra CLI lines or path segments."""
    if not isinstance(name, str) or not _INTERFACE_NAME.fullmatch(name):
        raise ValueError(f"invalid interface name: {name!r}")
    return name


def loopback_number(name):
    match = _LOOPBACK_NAME.fullmatch(name) if isinstance(name, str) else None
    if not match:
        raise ValueError(f"not a Loopback interface name: {name!r}")
    return int(match.group(1))


def split_ipv4(cidr):
    """Return (address, dotted netmask) for an address in CIDR notation."""
    interface = IPv4Interface(cidr)
    return str(interface.ip), str(interface.network.netmask)


def cidr_from(address, netmask=None, prefix_length=None):
    if prefix_length is None:
        prefix_length = IPv4Network(f"0.0.0.0/{netmask}").prefixlen
    return f"{address}/{int(prefix_length)}"
