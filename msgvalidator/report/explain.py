"""Plain-language explanations of findings (data/explain.yaml) for less experienced users."""
from __future__ import annotations

import fnmatch
import functools

import yaml

from ..resources import data_path


@functools.lru_cache(maxsize=1)
def _data() -> dict:
    with open(data_path("explain.yaml"), encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def severity(sev: str, lang: str = "cs") -> str:
    s = _data()["severity"].get(sev) or {}
    return s.get(lang) or s.get("cs") or ""


def rule(code: str | None, sev: str, lang: str = "cs") -> str | None:
    """Explanation of a finding code; None when there is none (the severity text then says enough)."""
    if not code:
        return None
    # KoSIT XSD messages carry their text in the code slot ("cvc-..."), normalise
    for r in _data()["rules"]:
        if r.get("sev") and r["sev"] != ("error" if sev == "fatal" else sev):
            continue
        if code == r["match"] or fnmatch.fnmatchcase(code, r["match"]):
            return r.get(lang) or r.get("cs")
    return None
