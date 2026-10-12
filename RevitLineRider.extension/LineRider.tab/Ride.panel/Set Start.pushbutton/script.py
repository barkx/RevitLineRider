# -*- coding: utf-8 -*-
"""Click where the sled starts in this view."""
__title__ = "Set\nStart"

from Autodesk.Revit.UI import TaskDialog
import linerider
linerider.fresh()   # always run the code that is on disk
from linerider import revitio, settings, game

uidoc = __revit__.ActiveUIDocument  # noqa: F821
view = uidoc.ActiveView
msg = revitio.check_view(view)
if msg:
    TaskDialog.Show("Line Rider", msg)
elif globals().get("__shiftclick__"):
    settings.set_view(uidoc.Document, view, start=None)
    game.notify_reload()
    TaskDialog.Show("Line Rider", "Start point cleared: the sled now starts above the highest line.")
else:
    frame = revitio.ViewFrame(uidoc.Document, view)
    p = revitio.pick_point(uidoc, view, "Line Rider: click where the sled should start")
    if p is not None:
        u, v = frame.uv(p)
        settings.set_view(uidoc.Document, view, start=[u, v])
        game.notify_reload()
