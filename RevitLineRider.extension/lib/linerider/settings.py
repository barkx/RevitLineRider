# -*- coding: utf-8 -*-
"""Small JSON settings store in %APPDATA%\\RevitLineRider\\settings.json"""
import io
import json
import os

_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "RevitLineRider")
_FILE = os.path.join(_DIR, "settings.json")

DEFAULTS = {
    "size": 1.0,          # rider size multiplier
    "follow": True,       # camera follows the rider
    "speed": 1.0,         # playback speed
    "left": False,        # ride to the left
    "hud": None,          # [left, top] of the HUD window
    "views": {},          # view key -> {"start": [u, v], "unit": ft}
}


def folder():
    if not os.path.isdir(_DIR):
        try:
            os.makedirs(_DIR)
        except Exception:
            pass
    return _DIR


def load():
    data = dict(DEFAULTS)
    data["views"] = {}
    try:
        with io.open(_FILE, "r", encoding="utf-8") as f:
            stored = json.loads(f.read())
        if isinstance(stored, dict):
            data.update(stored)
    except Exception:
        pass
    return data


def _plain(o):
    """Convert .NET numbers/strings (Int64, Double, String...) to plain Python."""
    if isinstance(o, dict):
        return dict((str(k), _plain(v)) for k, v in o.items())
    if isinstance(o, (list, tuple)):
        return [_plain(v) for v in o]
    if o is None or isinstance(o, (bool, float, str)):
        return o
    try:
        if isinstance(o, int):
            return int(o)
    except Exception:
        pass
    for conv in (int, float):
        try:
            v = conv(o)
            if conv is int and float(o) != v:
                continue
            return v
        except Exception:
            pass
    return u"%s" % o


def save(data):
    try:
        folder()
        text = json.dumps(_plain(data), indent=2, sort_keys=True)
        with io.open(_FILE, "w", encoding="utf-8") as f:
            f.write(u"%s" % text)
        return True
    except Exception as ex:
        log("settings save FAILED: %s" % ex)
        return False


def view_key(doc, view):
    try:
        name = doc.PathName or doc.Title
    except Exception:
        name = "?"
    return u"%s|%s" % (name, view.UniqueId)


def get_view(doc, view):
    return load()["views"].get(view_key(doc, view), {})


def set_view(doc, view, **values):
    data = load()
    rec = data["views"].setdefault(view_key(doc, view), {})
    for k, v in values.items():
        if v is None:
            rec.pop(k, None)
        else:
            rec[k] = v
    return save(data)


def log(msg):
    try:
        folder()
        import datetime
        with io.open(os.path.join(_DIR, "linerider.log"), "a", encoding="utf-8") as f:
            f.write(u"%s  %s\n" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass
