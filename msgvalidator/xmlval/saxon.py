"""Thin, thread-safe wrapper around saxonche (Saxon HE): compiled-stylesheet cache, XPath helper."""
from __future__ import annotations

import threading

LOCK = threading.RLock()  # SaxonC is not guaranteed thread-safe; the UI server is threaded
_proc = None
_xslt = None
_cache: dict[str, object] = {}


def processor():
    global _proc, _xslt
    if _proc is None:
        from saxonche import PySaxonProcessor
        _proc = PySaxonProcessor(license=False)
        _xslt = _proc.new_xslt30_processor()
    return _proc


def stylesheet(path: str):
    """Compiled XSLT executable, cached per path."""
    processor()
    exe = _cache.get(path)
    if exe is None:
        exe = _xslt.compile_stylesheet(stylesheet_file=path)
        _cache[path] = exe
    return exe


def parse(text: str, base_uri: str | None = None):
    return processor().parse_xml(xml_text=text)


def xpath_true(node, expr: str, namespaces: dict[str, str]) -> bool:
    """XPath 2.0/3.1 effective boolean value of expr evaluated on node."""
    xp = processor().new_xpath_processor()
    for prefix, uri in namespaces.items():
        xp.declare_namespace(prefix, uri)
    xp.set_context(xdm_item=node)
    val = xp.evaluate(expr)
    if val is None or val.size == 0:
        return False
    item = val.item_at(0)
    if val.size == 1 and item.is_atomic:
        return bool(item.get_atomic_value().boolean_value)
    return True
