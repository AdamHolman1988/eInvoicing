"""Startup splash (PyInstaller --splash) – no-ops when running from source."""
from __future__ import annotations

try:  # only available inside the frozen exe built with --splash
    import pyi_splash  # type: ignore
except ImportError:  # pragma: no cover
    pyi_splash = None


def text(msg: str) -> None:
    if pyi_splash is not None and pyi_splash.is_alive():
        pyi_splash.update_text(msg)


def close() -> None:
    if pyi_splash is not None and pyi_splash.is_alive():
        pyi_splash.close()


def prewarm() -> None:
    """Compile the default rule sets up front so the first check in the UI is fast."""
    try:
        from .xmlval import kosit, saxon
        repo = kosit.load("peppol")
        with saxon.LOCK:
            for sc in repo.scenarios[:2]:
                for _, path, _ in sc.schematron:
                    saxon.stylesheet(str(path))
                saxon.stylesheet(str(sc.report))
    except Exception:  # never block start-up because of warm-up
        pass
