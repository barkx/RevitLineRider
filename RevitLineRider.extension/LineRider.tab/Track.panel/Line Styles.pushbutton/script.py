# -*- coding: utf-8 -*-
"""Create the Line Rider line styles and optionally apply one to the selection."""
__title__ = "Line\nStyles"

from Autodesk.Revit.DB import CurveElement, Transaction
from Autodesk.Revit.UI import TaskDialog
from pyrevit import forms
import linerider
linerider.fresh()   # always run the code that is on disk
from linerider import revitio, game

uidoc = __revit__.ActiveUIDocument  # noqa: F821
doc = uidoc.Document
curves = [doc.GetElement(i) for i in uidoc.Selection.GetElementIds()]
curves = [c for c in curves if isinstance(c, CurveElement)]

LABELS = {
    "Track (blue, solid both sides)": "LR Track",
    "Accelerator (red, boosts in drawing direction)": "LR Accel",
    "One-way (purple, solid only on the ticked side)": "LR One-way",
    "Scenery (green, no collision)": "LR Scenery",
}

choice = None
if curves:
    choice = forms.CommandSwitchWindow.show(
        sorted(LABELS.keys()),
        message="Apply to %d selected line(s):" % len(curves))
    if not choice:
        curves = []

t = Transaction(doc, "Line Rider: line styles")
t.Start()
styles = revitio.ensure_styles(doc)
n = 0
for c in curves:
    try:
        c.LineStyle = styles[LABELS[choice]]
        n += 1
    except Exception:
        pass
t.Commit()
game.notify_reload()

if not curves:
    TaskDialog.Show(
        "Line Rider",
        "Line styles are ready:\n\n"
        "  LR Track - solid from both sides\n"
        "  LR Accel - speeds the sled up in the line's drawing direction\n"
        "  LR One-way - solid only from the left of the drawing direction\n"
        "      (draw left-to-right = ride on top; ticks show the solid side)\n"
        "  LR Scenery - drawn but never touched\n\n"
        "Any other line style counts as normal track. Select lines and click this "
        "button again to change their style.")
