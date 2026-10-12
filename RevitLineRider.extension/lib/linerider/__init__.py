# -*- coding: utf-8 -*-
"""Revit Line Rider - sled down your own detail lines.

physics.py and demo.py are pure Python. Everything else needs Revit."""
__version__ = "1.0.0"

try:
    import clr  # noqa
    # Revit 2025+ runs on .NET 8: IronPython only sees a minimal set of
    # assemblies, so reference everything the game uses explicitly.
    for _asm in ("RevitAPI", "RevitAPIUI", "WindowsBase", "PresentationCore",
                 "PresentationFramework", "System.Xaml", "System"):
        try:
            clr.AddReference(_asm)
        except Exception:
            pass
except ImportError:
    pass


def fresh():
    """Drop cached linerider modules so a button click always runs the code
    that is on disk now (pyRevit's persistent engine keeps old modules alive
    after the extension files are updated). A running game is closed through
    an AppDomain Action, which works across code versions."""
    import sys
    pkg = sys.modules.get("linerider")
    for name in list(sys.modules):
        if name.startswith("linerider."):
            del sys.modules[name]
            short = name.split(".", 1)[1]
            if pkg is not None and hasattr(pkg, short):
                try:
                    delattr(pkg, short)
                except Exception:
                    pass
