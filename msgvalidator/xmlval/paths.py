"""Helpers for SVRL / XPath locations."""
from __future__ import annotations

import re

_Q = re.compile(r"Q\{[^}]*\}")
_ISO = re.compile(r"\*:([\w.-]+)\[namespace-uri\(\)='[^']*'\]")


def readable(location: str | None) -> str | None:
    """'/Q{urn:..}Invoice[1]/Q{..}InvoiceLine[2]/@Q{}unitCode' -> '/Invoice/InvoiceLine[2]/@unitCode'."""
    if not location:
        return None
    s = _ISO.sub(r"\1", location)
    s = _Q.sub("", s)
    s = re.sub(r"@\*\[local-name\(\)='([\w.-]+)'\]", r"@\1", s)
    s = re.sub(r"\[1\]", "", s)
    return s
