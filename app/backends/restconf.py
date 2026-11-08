from urllib.parse import quote

import requests

from app.backends import planning
from app.backends.common import (
    AUTH_FAILED,
    BACKEND_FAILED,
    applied_response,
    cidr_from,
    error_from_exception,
    error_response,
    found_response,
    loopback_number,
    not_found_response,
    router_credentials,
    split_ipv4,
)

TIMEOUT = 15
JSON_TYPE = "application/yang-data+json"


def _default_get(url):
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    return requests.get(
        url,
        auth=router_credentials(),
        headers={"Accept": JSON_TYPE},
        verify=False,
        timeout=TIMEOUT,
    )


def _default_put(url, json):
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    return requests.put(
        url,
        json=json,
        auth=router_credentials(),
        headers={"Accept": JSON_TYPE, "Content-Type": JSON_TYPE},
        verify=False,
        timeout=TIMEOUT,
    )


def _normalize(raw):
    body = raw["ietf-interfaces:interface"]
    if isinstance(body, list):
        body = body[0]

    ipv4 = None
    addresses = (body.get("ietf-ip:ipv4") or {}).get("address") or []
    if isinstance(addresses, dict):
        addresses = [addresses]
    if addresses:
        first = addresses[0]
        ipv4 = cidr_from(
            first["ip"],
            netmask=first.get("netmask"),
            prefix_length=first.get("prefix-length"),
        )

    return {
        "name": body["name"],
        "ipv4": ipv4,
        "description": body.get("description"),
        "admin_state": "down" if body.get("enabled") is False else "up",
    }


def get_interface_state(
    router,
    interface_name,
    http_get=None,
):
    """Return normalized interface status using RESTCONF."""
    http_get = http_get or _default_get
    url = (
        f"https://{router}/restconf/data/"
        f"ietf-interfaces:interfaces/interface={quote(interface_name, safe='')}"
    )
    try:
        response = http_get(url)
        code = response.status_code
        if code == 404:
            return not_found_response()
        if code in (401, 403):
            return error_response(AUTH_FAILED)
        if code != 200:
            return error_response(BACKEND_FAILED)
        return found_response(_normalize(response.json()))
    except Exception as exc:
        return error_from_exception(exc)


def plan_interface(
    router,
    desired_interface,
    http_get=None,
):
    """Return create/update/no_change plan using RESTCONF status."""
    return planning.plan_interface(
        router,
        desired_interface,
        lambda r, name: get_interface_state(r, name, http_get),
    )


def apply_interface(
    router,
    desired_interface,
    http_put=None,
):
    """Apply complete desired interface state using RESTCONF."""
    http_put = http_put or _default_put
    try:
        number = loopback_number(desired_interface["name"])
        address, mask = split_ipv4(desired_interface["ipv4"])
        payload = {
            "name": number,
            "description": desired_interface["description"],
            "ip": {"address": {"primary": {"address": address, "mask": mask}}},
        }
        if desired_interface["admin_state"] == "down":
            payload["shutdown"] = [None]
        url = (
            f"https://{router}/restconf/data/"
            f"Cisco-IOS-XE-native:native/interface/Loopback={number}"
        )
        response = http_put(url, json={"Cisco-IOS-XE-native:Loopback": payload})
        code = response.status_code
        if code in (200, 201, 204):
            return applied_response()
        if code in (401, 403):
            return error_response(AUTH_FAILED)
        return error_response(BACKEND_FAILED)
    except Exception as exc:
        return error_from_exception(exc)
