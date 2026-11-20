"""Tiny selector language over the EDIFACT group tree.

    path   := step (" > " step)*
    step   := TAG [ "[" cond (";" cond)* "]" ]
    cond   := POS "=" V1 "|" V2 ...     value is one of
            | POS "!=" V1 "|" ...       value is none of
            | POS                       value is present
            | "!" POS                   value is absent
    POS    := element "." component     (1-based, element 1 = first after the tag)

A step matches a direct child of the current context: either a segment with that tag
or a segment group whose trigger segment has that tag (the conditions are tested on
the trigger). When a group matches, the next step searches inside that group.

Example: ``NAD[1.1=SU|SE] > RFF[1.1=VA]`` with value ``1.2`` -> seller VAT number.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from ..edifact.parser import Segment
from ..edifact.structure import GroupInstance

STEP_RE = re.compile(r"^([A-Za-z_][\w.\-]{0,63})(?:\[(.*)\])?$")  # EDIFACT NAD, flat HDR, IDoc E1EDKA1


@dataclass(frozen=True)
class Cond:
    elem: int
    comp: int
    op: str  # "in" | "notin" | "present" | "absent"
    values: tuple[str, ...] = ()

    def test(self, seg: Segment) -> bool:
        v = seg.get(self.elem, self.comp)
        if self.op == "present":
            return v is not None
        if self.op == "absent":
            return v is None
        if self.op == "in":
            return v in self.values
        return v not in self.values


@dataclass(frozen=True)
class Step:
    tag: str
    conds: tuple[Cond, ...]

    def test(self, seg: Segment) -> bool:
        return seg.tag == self.tag and all(c.test(seg) for c in self.conds)


def _pos(s: str) -> tuple[int, int]:
    e, _, c = s.strip().partition(".")
    return int(e), int(c or 1)


def _cond(s: str) -> Cond:
    s = s.strip()
    if "!=" in s:
        p, v = s.split("!=", 1)
        return Cond(*_pos(p), "notin", tuple(v.split("|")))
    if "=" in s:
        p, v = s.split("=", 1)
        return Cond(*_pos(p), "in", tuple(v.split("|")))
    if s.startswith("!"):
        return Cond(*_pos(s[1:]), "absent")
    return Cond(*_pos(s), "present")


@lru_cache(maxsize=None)
def compile_path(path: str) -> tuple[Step, ...]:
    steps = []
    for raw in path.split(">"):
        m = STEP_RE.match(raw.strip())
        if not m:
            raise ValueError(f"Invalid selector step {raw!r} in {path!r}")
        tag, conds = m.groups()
        steps.append(Step(tag, tuple(_cond(c) for c in conds.split(";")) if conds else ()))
    return tuple(steps)


def select(contexts: list, path: str) -> list:
    """Return matching nodes (Segment or GroupInstance) for the path, in document order.

    The special path ``@`` (optionally ``@ > STEP ...``) addresses the context group itself.
    """
    current = list(contexts)
    path = path.strip()
    if path.startswith("@"):
        head, _, rest = path.partition(">")
        head = head.strip()
        if head.startswith("@["):
            step = compile_path(node_segment(current[0]).tag + head[1:])[0] if current else None
            current = [c for c in current if step and step.test(node_segment(c))]
        if not rest.strip():
            return current
        path = rest
    steps = compile_path(path)
    for n, step in enumerate(steps):
        nxt = []
        for ctx in current:
            children = ctx.children if isinstance(ctx, GroupInstance) else []
            # the context group's own trigger is not a child "below" it
            start = 1 if isinstance(ctx, GroupInstance) and ctx.name != "ROOT" and ctx.name != "SCOPE" else 0
            for ch in children[start:]:
                seg = ch.trigger if isinstance(ch, GroupInstance) else ch
                if seg is not None and step.test(seg):
                    nxt.append(ch)
        current = nxt
    return current


def node_segment(node) -> Segment:
    return node.trigger if isinstance(node, GroupInstance) else node
