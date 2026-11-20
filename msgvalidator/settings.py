"""User settings (outside the exe): %APPDATA%\\MsgValidator\\settings.json.

* ``mapping_dir`` – folder with client mappings (YAML). Point it to a shared folder (OneDrive / SharePoint
  sync, network drive) so that the whole team uses the same client profiles.
  Environment variable MSGVALIDATOR_MAPPINGS overrides it.
"""
from __future__ import annotations

import json
import os
import pathlib


def home() -> pathlib.Path:
    base = os.environ.get("APPDATA") or str(pathlib.Path.home())
    return pathlib.Path(base) / "MsgValidator"


def _file() -> pathlib.Path:
    return home() / "settings.json"


def load() -> dict:
    try:
        return json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(values: dict) -> None:
    cur = load()
    cur.update(values)
    _file().parent.mkdir(parents=True, exist_ok=True)
    _file().write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")


def mapping_dir() -> pathlib.Path:
    d = os.environ.get("MSGVALIDATOR_MAPPINGS") or load().get("mapping_dir")
    return pathlib.Path(d) if d else home() / "mapovani"
