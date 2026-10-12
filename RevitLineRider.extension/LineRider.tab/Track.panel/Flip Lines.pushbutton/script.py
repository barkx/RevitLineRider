# -*- coding: utf-8 -*-
"""Reverse the drawing direction of the selected lines."""
__title__ = "Flip\nLines"

from Autodesk.Revit.DB import CurveElement, Transaction
from Autodesk.Revit.UI import TaskDialog
import linerider
linerider.fresh()   # always run the code that is on disk
from linerider import game

uidoc = __revit__.ActiveUIDocument  # noqa: F821
doc = uidoc.Document
curves = [doc.GetElement(i) for i in uidoc.Selection.GetElementIds()]
curves = [c for c in curves if isinstance(c, CurveElement)]
if not curves:
    TaskDialog.Show("Line Rider", "Select the accelerator or one-way lines to flip first.")
else:
    t = Transaction(doc, "Line Rider: flip lines")
    t.Start()
    ok, bad = 0, 0
    for c in curves:
        try:
            c.SetGeometryCurve(c.GeometryCurve.CreateReversed(), True)
            ok += 1
        except Exception:
            bad += 1
    t.Commit()
    game.notify_reload()
    if bad:
        TaskDialog.Show("Line Rider", "Flipped %d line(s). %d could not be flipped "
                        "(arcs sometimes refuse; redraw them in the other direction)." % (ok, bad))
