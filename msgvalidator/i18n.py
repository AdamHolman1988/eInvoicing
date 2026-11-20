"""Czech / English output.

The code and data are written in Czech; English is produced at the output boundary from the phrase table
data/i18n/en.yaml (Czech phrase -> English), longest phrase first, whole words only.
Official rule texts (KoSIT / CEN / Peppol / SK CIUS / BR-DE) stay in the language of their publisher.
"""
from __future__ import annotations

import re
from functools import lru_cache

import yaml

from .resources import data_path

LANGS = ("cs", "en")
WORD = r"0-9A-Za-zÀ-ž"


@lru_cache(maxsize=1)
def _table():
    raw = yaml.safe_load(data_path("i18n", "en.yaml").read_text(encoding="utf-8")) or {}
    pairs = {k.strip(): v for k, v in raw.items() if k and v and k.strip()}
    keys = sorted(pairs, key=len, reverse=True)
    parts = []
    for k in keys:
        pat = re.escape(k)
        if re.match(rf"[{WORD}]", k[0]):
            pat = rf"(?<![{WORD}])" + pat
        if re.match(rf"[{WORD}]", k[-1]):
            pat += rf"(?![{WORD}])"
        parts.append(pat)
    rx = re.compile("|".join(parts)) if parts else None
    return rx, pairs


def tr(text, lang: str = "cs"):
    """Translate a text (or None) to the target language."""
    if lang != "en" or not text or not isinstance(text, str):
        return text
    rx, pairs = _table()
    return rx.sub(lambda m: pairs[m.group(0)], text) if rx else text


def norm(lang: str | None) -> str:
    return lang if lang in LANGS else "cs"


def localize(rep, lang: str) -> None:
    """Translate a validation Report in place (labels, finding messages and hints)."""
    if lang != "en":
        return
    from .validate import TARGETS  # noqa: F401 – labels of target standards are in the table
    rep.detection.label = tr(rep.detection.label, lang)
    rep.detection.note = tr(rep.detection.note, lang)
    import dataclasses
    rep.profiles = [dataclasses.replace(p, name=tr(p.name, lang), description=tr(p.description, lang))
                    for p in rep.profiles]  # profiles are cached – never mutate them

    def fix(fs):
        for f in fs:
            f.message, f.hint = tr(f.message, lang), tr(f.hint, lang)
            f.contexts = [tr(c, lang) for c in f.contexts]
            f.profiles = [tr(x, lang) for x in f.profiles]
            f.name_sk = None  # Slovak term names make no sense in English output
    fix(rep.envelope)
    for m in rep.messages:
        m.label = tr(m.label, lang)
        for fs in (m.structure, m.values, m.gaps, m.rules):
            fix(fs)
        for fs in m.profiles.values():
            fix(fs)
        if m.rules_info:
            for r in m.rules_info.get("runs", []):
                r["label"], r["note"], r["scenario"] = tr(r["label"], lang), tr(r.get("note"), lang), tr(r["scenario"], lang)
            m.rules_info["scenario"] = tr(m.rules_info.get("scenario"), lang)
