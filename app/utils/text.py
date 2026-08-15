import re

CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
CONTROL_RE_STRICT = re.compile(r"[\x00-\x1f\x7f]")


def strip_control(value: str) -> str:
    if not value:
        return ""
    return CONTROL_RE.sub("", value)


def strip_control_strict(value: str) -> str:
    if not value:
        return ""
    return CONTROL_RE_STRICT.sub("", value)