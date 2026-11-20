"""Standard SAP IDoc mapping + client mappings (YAML files in the shared mapping folder).

A client mapping overrides the standard one per business term::

    id: company-sk
    name: Company, s.r.o.
    base: idoc_invoic_sap
    match:                         # applied automatically when all conditions hold
      EDI_DC40.SNDPRN: TESCLNT100
      E1EDK01.EIGENUINR: SK2020441654
    terms:
      BT-27: [{path: "E1EDKA1[PARVW=BK]", value: NAME1}]
      BT-35: []                    # empty list = the client's format does not carry it
    groups: {}                     # e.g. BG-23: {each: "E1EDS01[SUMID=030|031|032]", ...}
    aux: {}
"""
from __future__ import annotations

import copy
import datetime as dt
import re
import unicodedata
from functools import lru_cache

import yaml

from .. import settings
from ..flat.mapping import AUTO_ADD, resolve_records
from ..resources import data_path

STANDARD = "idoc_invoic_sap"
GENERIC = "xml_generic"  # unknown XML: empty start, everything comes from the client mapping
BASES = (STANDARD, GENERIC)
ID_RE = re.compile(r"[^a-z0-9]+")


@lru_cache(maxsize=None)
def _standard(name: str) -> dict:
    return yaml.safe_load(data_path("mappings", f"{name}.yaml").read_text(encoding="utf-8"))


def standard(name: str = STANDARD) -> dict:
    return copy.deepcopy(_standard(name))


def slug(name: str) -> str:
    plain = unicodedata.normalize("NFKD", name.lower()).encode("ascii", "ignore").decode()
    return ID_RE.sub("-", plain).strip("-") or "klient"


def clients() -> list[dict]:
    """All client mappings in the mapping folder (invalid files are reported, not raised)."""
    d = settings.mapping_dir()
    out = []
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.yaml")):
        try:
            c = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as ex:
            out.append({"id": p.stem, "name": p.stem, "error": str(ex), "file": str(p)})
            continue
        if c.get("base", STANDARD) not in BASES:
            continue
        c.setdefault("id", p.stem)
        c.setdefault("name", c["id"])
        c["file"] = str(p)
        out.append(c)
    return out


def get_client(cid: str) -> dict | None:
    return next((c for c in clients() if c["id"] == cid and "error" not in c), None)


def _matches(client: dict, msg) -> int:
    """Number of satisfied conditions, or -1 when a condition fails / there are none."""
    cond = client.get("match") or {}
    if not cond:
        return -1
    for key, want in cond.items():
        tag, _, fld = key.partition(".")
        have = (msg.value(tag, fld) or "").strip()
        wants = [str(w).strip() for w in (want if isinstance(want, list) else [want])]
        if have not in wants:
            return -1
    return len(cond)


def base_for(msg) -> str:
    return GENERIC if getattr(msg, "generic", False) else STANDARD


def pick(msg) -> dict | None:
    base = base_for(msg)
    scored = [(_matches(c, msg), c) for c in clients() if "error" not in c and c.get("base", STANDARD) == base]
    scored = [x for x in scored if x[0] > 0]
    return max(scored, key=lambda x: x[0])[1] if scored else None


def effective(client: dict | None, base: str = STANDARD) -> dict:
    """Standard (or generic) mapping with the client's overrides applied."""
    mp = standard((client or {}).get("base") or base)
    if not client:
        return mp
    for bt, rules in (client.get("terms") or {}).items():
        if rules:
            mp["terms"][bt] = rules
        else:
            mp["terms"].pop(bt, None)
    for bg, cfg in (client.get("groups") or {}).items():
        if cfg:
            mp["groups"][bg] = {**mp["groups"].get(bg, {}), **cfg}
        else:
            mp["groups"].pop(bg, None)
    for key, cfg in (client.get("aux") or {}).items():
        mp.setdefault("aux", {})[key] = cfg
    for key, cfg in (client.get("computed") or {}).items():  # terms / groups computed from others (guess/arith.py)
        if cfg:
            mp.setdefault("computed", {})[key] = cfg
        else:
            (mp.get("computed") or {}).pop(key, None)
    cid = client.get("id") or slug(client.get("name") or "koncept")
    mp["id"] = f"{mp['id']}+{cid}"
    mp["client"] = {"id": cid, "name": client.get("name") or cid}
    return mp


def resolve_for(msg, mp: dict) -> dict:
    records = msg.records()
    records[AUTO_ADD] = True
    return resolve_records(mp, records)


def suggest_match(msg) -> dict:
    """Conditions that identify the sender: SAP system of the sender + seller VAT ID (generic XML: root element)."""
    if getattr(msg, "generic", False):
        return {"ROOT": msg.root_tag}
    out = {}
    for key in ("EDI_DC40.SNDPRN", "E1EDK01.EIGENUINR"):
        tag, _, fld = key.partition(".")
        v = msg.value(tag, fld)
        if v:
            out[key] = v
    return out


def save_client(client: dict, author: str | None = None) -> str:
    """Write a client mapping; returns the file path. Only the keys of the client format are kept."""
    d = settings.mapping_dir()
    d.mkdir(parents=True, exist_ok=True)
    cid = slug(client.get("id") or client.get("name") or "klient")
    data = {
        "id": cid,
        "name": client.get("name") or cid,
        "base": client.get("base", STANDARD),
        "note": client.get("note") or None,
        "updated": dt.datetime.now().isoformat(timespec="minutes") + (f" ({author})" if author else ""),
        "match": client.get("match") or {},
        "terms": client.get("terms") or {},
        "groups": client.get("groups") or {},
        "aux": client.get("aux") or {},
        "computed": client.get("computed") or {},
    }
    data = {k: v for k, v in data.items() if v not in (None, {})}
    path = d / f"{cid}.yaml"
    header = ("# Klientské mapování MsgValidatoru (SAP IDoc). Upravujte v aplikaci: záložka Mapování.\n"
              "# Přepisuje standardní mapování po jednotlivých BT; prázdný seznam = údaj klient neposílá.\n")
    path.write_text(header + yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    return str(path)
