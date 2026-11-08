import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

from app.backends import planning
from app.backends.common import (
    applied_response,
    cidr_from,
    error_from_exception,
    found_response,
    loopback_number,
    not_found_response,
    router_credentials,
    split_ipv4,
)

IETF_INTERFACES = "urn:ietf:params:xml:ns:yang:ietf-interfaces"
IETF_IP = "urn:ietf:params:xml:ns:yang:ietf-ip"
PORT = 830
TIMEOUT = 30


def _connect(router):
    from ncclient import manager

    user, password = router_credentials()
    return manager.connect(
        host=router,
        port=PORT,
        username=user,
        password=password,
        hostkey_verify=False,
        look_for_keys=False,
        allow_agent=False,
        timeout=TIMEOUT,
    )


def _default_get_config(router, filter_xml):
    with _connect(router) as session:
        reply = session.get_config(source="running", filter=("subtree", filter_xml))
        return reply.data_xml


def _default_edit_config(router, config_xml):
    with _connect(router) as session:
        session.edit_config(target="running", config=config_xml)


def _text(element):
    if element is None or element.text is None:
        return None
    return element.text.strip()


def _normalize(xml_text, interface_name):
    root = ET.fromstring(xml_text)
    ns = {"i": IETF_INTERFACES, "ip": IETF_IP}
    for interface in root.iter(f"{{{IETF_INTERFACES}}}interface"):
        if _text(interface.find("i:name", ns)) != interface_name:
            continue

        ipv4 = None
        address = interface.find("ip:ipv4/ip:address", ns)
        if address is not None:
            ip = _text(address.find("ip:ip", ns))
            netmask = _text(address.find("ip:netmask", ns))
            prefix = _text(address.find("ip:prefix-length", ns))
            if ip:
                ipv4 = cidr_from(ip, netmask=netmask, prefix_length=prefix)

        return {
            "name": interface_name,
            "ipv4": ipv4,
            "description": _text(interface.find("i:description", ns)),
            "admin_state": (
                "down" if _text(interface.find("i:enabled", ns)) == "false" else "up"
            ),
        }
    return None


def get_interface_state(
    router,
    interface_name,
    netconf_get_config=None,
):
    """Return normalized interface status using NETCONF."""
    netconf_get_config = netconf_get_config or _default_get_config
    filter_xml = (
        f'<interfaces xmlns="{IETF_INTERFACES}"><interface>'
        f"<name>{escape(interface_name)}</name>"
        "</interface></interfaces>"
    )
    try:
        interface = _normalize(
            netconf_get_config(router, filter_xml), interface_name
        )
    except Exception as exc:
        return error_from_exception(exc)
    if interface is None:
        return not_found_response()
    return found_response(interface)


def plan_interface(
    router,
    desired_interface,
    netconf_get_config=None,
):
    """Return create/update/no_change plan using NETCONF status."""
    return planning.plan_interface(
        router,
        desired_interface,
        lambda r, name: get_interface_state(r, name, netconf_get_config),
    )


def apply_interface(
    router,
    desired_interface,
    netconf_edit_config=None,
):
    """Apply complete desired interface state using NETCONF."""
    netconf_edit_config = netconf_edit_config or _default_edit_config
    try:
        number = loopback_number(desired_interface["name"])
        address, mask = split_ipv4(desired_interface["ipv4"])
        shutdown = "<shutdown/>" if desired_interface["admin_state"] == "down" else ""
        config_xml = (
            '<config xmlns="urn:ietf:params:xml:ns:netconf:base:1.0" '
            'xmlns:nc="urn:ietf:params:xml:ns:netconf:base:1.0">'
            '<native xmlns="http://cisco.com/ns/yang/Cisco-IOS-XE-native">'
            "<interface>"
            '<Loopback nc:operation="replace">'
            f"<name>{number}</name>"
            f"<description>{escape(desired_interface['description'])}</description>"
            "<ip><address><primary>"
            f"<address>{address}</address><mask>{mask}</mask>"
            "</primary></address></ip>"
            f"{shutdown}"
            "</Loopback></interface></native></config>"
        )
        netconf_edit_config(router, config_xml)
    except Exception as exc:
        return error_from_exception(exc)
    return applied_response()
