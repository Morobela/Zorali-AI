DENYLIST = ["rm -rf", "mkfs", "shutdown", "reboot", "del /s", "credential", "passwd", "format "]


def validate_command(command: str) -> tuple[bool, str]:
    lower = command.lower()
    for blocked in DENYLIST:
        if blocked in lower:
            return False, f"Blocked dangerous command pattern: {blocked}"
    return True, "ok"
