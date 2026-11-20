"""Semantic (EN 16931) view of a parsed message."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Value:
    bt: str
    value: str
    how: str = "explicit"  # explicit | mapped | derived | ambiguous | const
    line: int | None = None
    segment: str | None = None
    raw: str | None = None  # value before code mapping
    scheme: str | None = None
    note: str | None = None
    rule: str | None = None  # selector / derive name that produced the value


@dataclass
class Context:
    """One evaluation context: the document header or one instance of a repeating group."""
    bg: str | None  # None = document level, else BG-25 / BG-23 / BG-20 / BG-21
    label: str
    line: int | None
    values: dict[str, list[Value]] = field(default_factory=dict)
    parent: "Context | None" = None  # e.g. the invoice line of a line-level charge (BG-28)
    aux: dict[str, Value] = field(default_factory=dict)  # non-BT helper facts, e.g. item_type (Z/O/S)
    index: int | None = None  # 1-based position of a repeating-group instance

    def add(self, v: Value) -> None:
        self.values.setdefault(v.bt, []).append(v)

    def has(self, bt: str) -> bool:
        return bool(self.values.get(bt))


@dataclass
class Semantic:
    source_format: str  # e.g. "EDIFACT INVOIC D01B"
    mapping_id: str
    document: Context
    groups: dict[str, list[Context]]  # repeating BG id -> instances
    mapped_terms: set[str]  # BTs the mapping knows how to fill (can be carried by the format)
    rules: dict[str, list[dict]]  # mapping rules per BT (for "expected at" hints)
    repeating: dict[str, str]  # BT -> repeating BG it lives in
    notes: list[dict] = field(default_factory=list)  # informational remarks from extraction
    doc_kind: str = "Invoice"  # Invoice | CreditNote (from BT-3)

    def contexts(self):
        yield self.document
        for insts in self.groups.values():
            yield from insts
