# -*- coding: utf-8 -*-
"""Draw the demo course in the active view and start riding."""
__persistentengine__ = True
__title__ = "Demo\nTrack"

from Autodesk.Revit.UI import (TaskDialog, TaskDialogCommonButtons, TaskDialogResult)
import linerider
linerider.fresh()   # always run the code that is on disk
from linerider import revitio, settings, game

uiapp = __revit__  # noqa: F821
uidoc = uiapp.ActiveUIDocument
doc = uidoc.Document
view = uidoc.ActiveView
msg = revitio.check_view(view)
if msg:
    TaskDialog.Show("Line Rider", msg)
else:
    game.close_existing()
    frame = revitio.ViewFrame(doc, view)
    unit = revitio.default_unit(view)
    rec = settings.get_view(doc, view)
    old_ids = [int(i) for i in (rec.get("demo_ids") or [])]

    # lines with LR styles that this demo didn't make (earlier versions,
    # or the user's own): offer to remove them so they don't get in the way
    known = set(old_ids)
    stray = [i for i in revitio.lr_styled_lines(doc, view) if i not in known]
    if stray:
        td = TaskDialog("Line Rider")
        td.MainInstruction = "Remove %d older Line Rider lines?" % len(stray)
        td.MainContent = ("This view already has %d lines with the LR Track / Accel / One-way / "
                          "Scenery styles (probably earlier demo tracks).\n\n"
                          "Yes: delete them, so only the new demo is in the view.\n"
                          "No: keep them; the new demo is drawn next to them." % len(stray))
        td.CommonButtons = TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No | TaskDialogCommonButtons.Cancel
        td.DefaultButton = TaskDialogResult.Yes
        res = td.Show()
        if res == TaskDialogResult.Cancel:
            stray = None
        elif res == TaskDialogResult.Yes:
            old_ids += stray
    if stray is not None:
        center = revitio.visible_center_uv(uidoc, view, frame)
        existing = revitio.read_track_uv(doc, view, frame)
        start, bbox, count, ids = revitio.draw_demo(
            doc, view, frame, center, unit, existing_polys=existing, old_ids=old_ids)
        ok = settings.set_view(doc, view, start=[start[0], start[1]], unit=unit, demo_ids=ids)
        cfg = settings.load()
        cfg["follow"] = True          # the course is long: let the camera follow
        cfg["size"] = 1.0             # the course is validated at size x1
        cfg["left"] = False
        settings.save(cfg)
        settings.log("demo drawn in view %s: %d lines, unit %.4f ft, start (%.2f, %.2f), saved=%s"
                     % (view.Name, count, unit, start[0], start[1], ok))
        # hand the start over directly, so the game never depends on the file
        g = game.launch(uiapp, start=start, unit=unit)
        if g is not None:
            g.status = u"DEMO READY – press Space"
            g.update_hud()
