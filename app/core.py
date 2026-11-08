import yaml

ALLOWED_ROUTERS = (
    "10.0.29.101",
    "10.0.29.102",
    "10.0.29.103",
    "10.0.29.104",
    "10.0.29.105",
)

METHOD_ACTIONS = {
    "restconf": ("status", "plan", "apply"),
    "netconf": ("status", "plan", "apply"),
    "ansible": ("apply",),
    "netmiko-textfsm": ("status", "delete"),
}

ADMIN_STATES = ("up", "down")


def _error(result):
    return {"status": "error", "result": result}


def _absent(mapping, key):
    return key not in mapping or mapping[key] is None


def validate_request(data):
    """
    Validate one IPA2026 desired-state request.

    Return a response dictionary according to
    specs/response-spec-v1.md.
    """
    if not isinstance(data, dict):
        return _error("invalid_yaml")

    version = data.get("version")
    if type(version) is not int or version != 1:
        return _error("invalid_version")

    if _absent(data, "router"):
        return _error("missing_router")
    router = data["router"]
    if not isinstance(router, str) or router not in ALLOWED_ROUTERS:
        return _error("invalid_router")

    if _absent(data, "method"):
        return _error("missing_method")
    method = data["method"]
    if not isinstance(method, str) or method not in METHOD_ACTIONS:
        return _error("invalid_method")

    if _absent(data, "action"):
        return _error("missing_action")
    action = data["action"]
    if not isinstance(action, str) or action not in METHOD_ACTIONS[method]:
        return _error("invalid_action")

    desired = data.get("desired")
    if not isinstance(desired, dict):
        return _error("missing_desired")
    interface = desired.get("interface")
    if not isinstance(interface, dict):
        return _error("missing_interface")
    name = interface.get("name")
    if not isinstance(name, str) or not name.strip():
        return _error("missing_interface_name")

    if action in ("plan", "apply"):
        if _absent(interface, "ipv4"):
            return _error("missing_ipv4")
        if _absent(interface, "description"):
            return _error("missing_description")
        if _absent(interface, "admin_state"):
            return _error("missing_admin_state")
        state = interface["admin_state"]
        if not isinstance(state, str) or state not in ADMIN_STATES:
            return _error("invalid_admin_state")

    return {"status": "ok", "result": "accepted"}


def load_request_file(path):
    """Parse a YAML request file. Return (data, error_response)."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return None, _error("invalid_yaml")
    if not isinstance(data, dict):
        return None, _error("invalid_yaml")
    return data, None


def process_request_file(path):
    """
    Read a YAML request file, validate it,
    and return a response dictionary.
    """
    data, error = load_request_file(path)
    if error is not None:
        return error
    return validate_request(data)
