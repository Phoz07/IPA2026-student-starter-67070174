import json
import os
import shutil
import subprocess
from pathlib import Path

from app.backends.common import (
    applied_response,
    error_from_exception,
    split_ipv4,
    validate_interface_name,
)

ANSIBLE_DIR = Path(__file__).resolve().parents[2] / "ansible"
TIMEOUT = 180


def _default_run_playbook(variables):
    executable = shutil.which("ansible-playbook")
    if executable is None:
        raise RuntimeError("ansible-playbook is not installed")

    env = dict(os.environ, ANSIBLE_HOST_KEY_CHECKING="False", ANSIBLE_NOCOLOR="1")
    try:
        completed = subprocess.run(
            [
                executable,
                "-i",
                str(ANSIBLE_DIR / "inventory.ini"),
                str(ANSIBLE_DIR / "apply_interface.yml"),
                "--extra-vars",
                json.dumps(variables),
            ],
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            env=env,
            cwd=str(ANSIBLE_DIR),
        )
    except subprocess.TimeoutExpired as exc:
        raise ConnectionError("ansible-playbook timed out") from exc

    if completed.returncode == 0:
        return
    output = (completed.stdout + completed.stderr).lower()
    if any(
        marker in output
        for marker in (
            "authentication failed",
            "invalid/incorrect password",
            "permission denied",
            "authentication failure",
        )
    ):
        raise PermissionError("router rejected credentials")
    if completed.returncode == 4 or "unreachable" in output:
        raise ConnectionError("router unreachable")
    raise RuntimeError("playbook failed")


def apply_interface(
    router,
    desired_interface,
    run_playbook=None,
):
    """Apply complete desired interface state using Ansible."""
    run_playbook = run_playbook or _default_run_playbook
    try:
        validate_interface_name(desired_interface["name"])
        description = desired_interface["description"]
        if any(ord(char) < 32 for char in str(description)):
            raise ValueError("description contains control characters")
        address, netmask = split_ipv4(desired_interface["ipv4"])
        run_playbook(
            {
                "router": router,
                "interface_name": desired_interface["name"],
                "description": str(description),
                "ipv4_address": address,
                "netmask": netmask,
                "shutdown": desired_interface["admin_state"] == "down",
            }
        )
    except Exception as exc:
        return error_from_exception(exc)
    return applied_response()
