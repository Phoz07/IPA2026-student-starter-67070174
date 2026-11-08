import re

from app.backends.common import (
    cidr_from,
    error_from_exception,
    found_response,
    not_found_response,
    router_credentials,
    validate_interface_name,
)

_NAME_PARTS = re.compile(r"([A-Za-z\-]+)([0-9/.]+)")


def _connect(router):
    from netmiko import ConnectHandler

    user, password = router_credentials()
    return ConnectHandler(
        device_type="cisco_ios",
        host=router,
        username=user,
        password=password,
        conn_timeout=15,
        auth_timeout=15,
    )


def _parsed(output):
    """TextFSM returns the raw string when nothing could be parsed."""
    return output if isinstance(output, list) else []


def _parse_show_ip_interface(raw, command):
    """Parse `show ip interface <name>` output with TextFSM.

    IOS answers "% Invalid input ..." when the interface does not exist.
    That text is not parseable (TextFSM raises), so treat it as no records.
    """
    if not raw.strip() or raw.lstrip().startswith("%") or "% Invalid input" in raw:
        return []
    from netmiko.utilities import get_structured_data

    return _parsed(get_structured_data(raw, platform="cisco_ios", command=command))


def _default_get(router, interface_name):
    validate_interface_name(interface_name)
    connection = _connect(router)
    try:
        command = f"show ip interface {interface_name}"
        ip_info = _parse_show_ip_interface(connection.send_command(command), command)
        descriptions = connection.send_command(
            "show interfaces description", use_textfsm=True
        )
    finally:
        connection.disconnect()
    return ip_info, _parsed(descriptions)


def _same_interface(short_or_long, interface_name):
    """Match 'Lo123' (or 'Loopback123') against 'Loopback123'."""
    left = _NAME_PARTS.fullmatch(str(short_or_long).strip())
    right = _NAME_PARTS.fullmatch(interface_name)
    if not left or not right or left.group(2) != right.group(2):
        return False
    return right.group(1).lower().startswith(left.group(1).lower())


def _first(value):
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    return value or None


def _normalize(ip_info, descriptions, interface_name):
    record = next(
        (
            item
            for item in ip_info
            if str(item.get("interface", "")).lower() == interface_name.lower()
        ),
        None,
    )
    if record is None:
        return None

    address = _first(record.get("ip_address"))
    prefix = _first(record.get("prefix_length"))
    ipv4 = cidr_from(address, prefix_length=prefix) if address and prefix else None

    description = None
    for item in descriptions:
        if _same_interface(item.get("port", ""), interface_name):
            description = item.get("description") or None
            break

    down = "administratively down" in str(record.get("link_status", "")).lower()
    return {
        "name": interface_name,
        "ipv4": ipv4,
        "description": description,
        "admin_state": "down" if down else "up",
    }


def get_interface_state(
    router,
    interface_name,
    netmiko_get=None,
):
    """Return normalized interface status using Netmiko + TextFSM."""
    netmiko_get = netmiko_get or _default_get
    try:
        ip_info, descriptions = netmiko_get(router, interface_name)
        interface = _normalize(
            _parsed(ip_info), _parsed(descriptions), interface_name
        )
    except Exception as exc:
        return error_from_exception(exc)
    if interface is None:
        return not_found_response()
    return found_response(interface)


def _present(router, interface_name):
    """Status read that lets transport errors propagate for classification."""
    ip_info, descriptions = _default_get(router, interface_name)
    return _normalize(ip_info, descriptions, interface_name) is not None


def _default_delete(router, interface_name):
    validate_interface_name(interface_name)
    if _present(router, interface_name) is False:
        return "not_found"

    connection = _connect(router)
    try:
        output = connection.send_config_set([f"no interface {interface_name}"])
    finally:
        connection.disconnect()
    if "%" in output:
        raise RuntimeError(f"router rejected delete: {output}")

    if _present(router, interface_name):
        raise RuntimeError("interface still present after delete")
    return "deleted"


def delete_interface(
    router,
    interface_name,
    netmiko_delete=None,
):
    """Delete an interface using Netmiko."""
    netmiko_delete = netmiko_delete or _default_delete
    try:
        result = netmiko_delete(router, interface_name)
    except Exception as exc:
        return error_from_exception(exc)
    if result == "deleted":
        return {"status": "ok", "result": "deleted"}
    if result == "not_found":
        return not_found_response()
    return {"status": "error", "result": "backend_failed"}
