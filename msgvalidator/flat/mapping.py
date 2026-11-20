"""Mappings for flat files may address fields by name; this resolves them to element positions.

    path:  "NAD[PARTNER_KVALIF=SU|SE] > ..."   ->  "NAD[1.1=SU|SE]"
    value: "VAT_IC"                             ->  "15.1"
    join:  [OBCH_JM_1, OBCH_JM_2]               ->  ["3.1", "4.1"]
    format_at, args.value / args.flag            likewise (relative to the last step of the path)

Numeric positions ("15.1") are left untouched, so both styles can be mixed.
"""
from __future__ import annotations

import copy
import re
from functools import lru_cache

import yaml

from ..resources import data_path
from . import load_layout, virtual_records

STEP_RE = re.compile(r"^(@|[A-Za-z_][\w.\-]{0,63})(?:\[(.*)\])?$")
POS_RE = re.compile(r"^\d+(\.\d+)?$")


class MappingError(ValueError):
    pass


def _pos(records: dict, tag: str, name: str, where: str) -> str:
    name = name.strip()
    if POS_RE.match(name):
        return name
    for f in records.get(tag, {}).get("fields", []):
        if f["name"] == name:
            return f"{f['n'] - 1}.1"
    if records.get(AUTO_ADD):
        # open formats (SAP IDoc XML): a field the sample does not carry is simply absent, not a mapping error
        fields = records.setdefault(tag, {"fields": [{"n": 1, "name": "TAG"}]})["fields"]
        fields.append({"n": max(f["n"] for f in fields) + 1, "name": name})
        return f"{fields[-1]['n'] - 1}.1"
    raise MappingError(f"{where}: záznam {tag} nemá pole '{name}'.")


AUTO_ADD = "*auto_add*"


def _cond(records, tag, cond, where):
    cond = cond.strip()
    neg = cond.startswith("!")
    body = cond[1:] if neg else cond
    for op in ("!=", "="):
        if op in body:
            name, val = body.split(op, 1)
            return f"{_pos(records, tag, name, where)}{op}{val}"
    return ("!" if neg else "") + _pos(records, tag, body, where)


def resolve_path(records: dict, path: str, ctx_tag: str | None, where: str) -> tuple[str, str | None]:
    """Return (resolved path, tag of the last step)."""
    out, tag = [], ctx_tag
    for raw in path.split(">"):
        m = STEP_RE.match(raw.strip())
        if not m:
            raise MappingError(f"{where}: neplatný krok '{raw.strip()}'.")
        t, conds = m.groups()
        tag = ctx_tag if t == "@" else t
        if conds:
            conds = ";".join(_cond(records, tag, c, where) for c in conds.split(";"))
            out.append(f"{t}[{conds}]")
        else:
            out.append(t)
    return " > ".join(out), tag


def resolve(mp: dict, layout_id: str) -> dict:
    return resolve_records(mp, virtual_records(load_layout(layout_id)))


def _resolve_args(records, args: dict, ctx_tag, where: str) -> None:
    """Derivation arguments: path/value, flag_path/flag, and nested {path, value} dicts (any key)."""
    if "path" in args:
        args["path"], atag = resolve_path(records, args["path"], ctx_tag, where)
        if "value" in args:
            args["value"] = _pos(records, atag, args["value"], where)
    if "flag_path" in args:
        args["flag_path"], ftag = resolve_path(records, args["flag_path"], ctx_tag, where)
        args["flag"] = _pos(records, ftag, args["flag"], where)
    for k, v in args.items():
        if isinstance(v, dict) and "path" in v:
            _resolve_args(records, v, ctx_tag, f"{where}.{k}")


def _label(records, tpl: str, tag: str, where: str) -> str:
    """'řádek {POSEX}' -> 'řádek {1.1}'."""
    return re.sub(r"\{([^}]+)\}", lambda m: "{" + _pos(records, tag, m.group(1), where) + "}", tpl)


def resolve_records(mp: dict, records: dict) -> dict:
    mp = copy.deepcopy(mp)
    group_tag: dict[str, str] = {}
    for bg, cfg in mp.get("groups", {}).items():
        cfg["each"], group_tag[bg] = resolve_path(records, cfg["each"], None, bg)
        if cfg.get("label"):
            cfg["label"] = _label(records, cfg["label"], group_tag[bg], bg)

    from ..semantic.catalog import catalog
    cat = catalog()
    todo = [(bt, rules, next((group_tag[a] for a in cat.ancestors(bt) if a in group_tag), None))
            for bt, rules in mp["terms"].items()]
    todo += [(f"aux.{key}", cfg["rules"], group_tag.get(cfg.get("group")))
             for key, cfg in mp.get("aux", {}).items()]
    for bt, rules, ctx_tag in todo:
        for r in rules:
            where = f"{bt}"
            tag = ctx_tag
            if "path" in r:
                r["path"], tag = resolve_path(records, r["path"], ctx_tag, where)
            for key in ("value", "format_at"):
                if key in r:
                    r[key] = _pos(records, tag, r[key], where)
            if "join" in r:
                r["join"] = [_pos(records, tag, n, where) for n in r["join"]]
            if r.get("args"):
                _resolve_args(records, r["args"], ctx_tag, where)
    return mp


@lru_cache(maxsize=None)
def load(name: str) -> dict:
    mp = yaml.safe_load(data_path("mappings", f"{name}.yaml").read_text(encoding="utf-8"))
    return resolve(mp, mp["layout"])
