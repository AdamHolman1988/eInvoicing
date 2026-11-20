"""Locate bundled data files both in a source checkout and inside a PyInstaller exe."""
import pathlib
import sys


def base_dir() -> pathlib.Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return pathlib.Path(sys._MEIPASS) / "msgvalidator"
    return pathlib.Path(__file__).resolve().parent


def data_path(*parts: str) -> pathlib.Path:
    return base_dir().joinpath("data", *parts)
