# -*- coding: utf-8 -*-
"""Everything that reads or writes the Revit model: view geometry, track
lines, line styles, the demo track and picking points."""
from __future__ import division
import math

import linerider  # noqa: F401  (adds assembly references)
from Autodesk.Revit.DB import (
    BuiltInCategory, Color, CurveElement, ElementId, FilteredElementCollector,
    ElementTypeGroup, GraphicsStyleType, Line, Plane, SketchPlane, TextNote,
    Transaction, View3D, ViewPlan, ViewType, XYZ, PlanViewPlane)
from Autodesk.Revit.Exceptions import OperationCanceledException

from linerider import physics, demo, settings

SLED_MM = 12.0        # sled length on paper at size x1
FT_PER_MM = 1.0 / 304.8

STYLES = [
    # name, rgb, weight, kind
    ("LR Track",   (25, 75, 200), 4, physics.NORMAL),
    ("LR Accel",   (215, 35, 35), 4, physics.ACCEL_LINE),
    ("LR One-way", (125, 55, 190), 4, physics.ONEWAY),
    ("LR Scenery", (40, 160, 60), 1, None),
]
KIND_STYLE = {physics.NORMAL: "LR Track", physics.ACCEL_LINE: "LR Accel",
              physics.ONEWAY: "LR One-way"}


def eid_int(eid):
    """ElementId -> plain Python int (Value is a .NET Int64 in Revit 2024+,
    which json cannot write)."""
    try:
        return int(eid.Value)     # Revit 2024+
    except AttributeError:
        return int(eid.IntegerValue)


def kind_for_style(name):
    """Line style name -> line kind (None = no collision)."""
    n = (name or u"").lower()
    if "scenery" in n or "invisible" in n:
        return None
    if "accel" in n or "boost" in n:
        return physics.ACCEL_LINE
    if "one-way" in n or "oneway" in n or "one way" in n:
        return physics.ONEWAY
    return physics.NORMAL


SUPPORTED = (ViewType.FloorPlan, ViewType.CeilingPlan, ViewType.EngineeringPlan,
             ViewType.AreaPlan, ViewType.Section, ViewType.Elevation,
             ViewType.Detail, ViewType.DraftingView)


def check_view(view):
    if view is None:
        return u"No active view."
    if isinstance(view, View3D):
        return (u"Line Rider runs in 2D views: a plan, section, elevation or "
                u"drafting view. Open one and try again.")
    if view.ViewType not in SUPPORTED:
        return u"This view type (%s) is not supported. Use a plan, section, elevation or drafting view." % view.ViewType
    return None


# --------------------------------------------------------------------------
# view frame: Revit XYZ <-> (u, v) in the view plane
# --------------------------------------------------------------------------
class ViewFrame(object):
    def __init__(self, doc, view):
        self.R = view.RightDirection.Normalize()
        self.U = view.UpDirection.Normalize()
        self.D = view.ViewDirection.Normalize()
        origin = view.Origin
        detail = None
        try:
            if view.SketchPlane is not None:
                detail = view.SketchPlane.GetPlane().Origin
        except Exception:
            detail = None
        if isinstance(view, ViewPlan):
            z = None
            try:
                vr = view.GetViewRange()
                lvl = doc.GetElement(vr.GetLevelId(PlanViewPlane.CutPlane))
                z = lvl.ProjectElevation + vr.GetOffset(PlanViewPlane.CutPlane)
            except Exception:
                try:
                    z = view.GenLevel.ProjectElevation + 4.0
                except Exception:
                    z = 0.0
            origin = XYZ(origin.X, origin.Y, z)
            if detail is None:
                try:
                    detail = XYZ(0, 0, view.GenLevel.ProjectElevation)
                except Exception:
                    detail = XYZ(0, 0, 0)
        # rider geometry sits just behind the cut plane (inside the view depth)
        self.O = origin - self.D * 0.06
        self.detail_origin = detail if detail is not None else view.Origin

    def uv(self, p):
        d = p - self.O
        return d.DotProduct(self.R), d.DotProduct(self.U)

    def xyz(self, u, v, lift=0.0):
        return self.O + self.R * u + self.U * v + self.D * lift

    def detail_xyz(self, u, v):
        """A point on the view's own detail/work plane (for creating lines)."""
        base = self.detail_origin
        # move base so its (u, v) is zero, keeping its depth
        bu, bv = self.uv(base)
        return base + self.R * (u - bu) + self.U * (v - bv)


def default_unit(view, size=1.0):
    """Feet per rider unit so the sled is SLED_MM long on paper."""
    try:
        scale = max(1, view.Scale)
    except Exception:
        scale = 100
    return scale * SLED_MM / 17.5 * FT_PER_MM * size


# --------------------------------------------------------------------------
# track
# --------------------------------------------------------------------------
def read_track_uv(doc, view, frame):
    """Returns list of (kind, [(u, v), ...]) for every line visible in the view."""
    out = []
    lines_cat = eid_int(ElementId(BuiltInCategory.OST_Lines))
    col = FilteredElementCollector(doc, view.Id).OfClass(CurveElement)
    for ce in col:
        try:
            cat = ce.Category
            if cat is None or eid_int(cat.Id) != lines_cat:
                continue
            style = ce.LineStyle
            kind = kind_for_style(style.Name if style is not None else u"")
            if kind is None:
                continue
            curve = ce.GeometryCurve
            if curve is None:
                continue
            pts = [frame.uv(p) for p in curve.Tessellate()]
            if len(pts) >= 2:
                out.append((kind, pts, eid_int(ce.Id)))
        except Exception:
            continue
    return out


def lr_styled_lines(doc, view):
    """Ids of lines in the view that use one of the LR line styles (for
    cleaning up demos from older versions that didn't record their ids)."""
    names = set(st[0] for st in STYLES)
    out = []
    for ce in FilteredElementCollector(doc, view.Id).OfClass(CurveElement):
        try:
            style = ce.LineStyle
            if style is not None and style.Name in names:
                out.append(eid_int(ce.Id))
        except Exception:
            pass
    return out


def uv_bbox(polys):
    us = [p[0] for poly in polys for p in poly[1]]
    vs = [p[1] for poly in polys for p in poly[1]]
    if not us:
        return None
    return min(us), min(vs), max(us), max(vs)


def build_track(polys, u0, v0, unit):
    """(u, v) polylines -> physics.Track in rider units (y down, origin at start)."""
    segs = []
    for poly in polys:
        kind, pts = poly[0], poly[1]
        conv = [((u - u0) / unit, -(v - v0) / unit) for (u, v) in pts]
        for a, b in zip(conv[:-1], conv[1:]):
            if abs(a[0] - b[0]) + abs(a[1] - b[1]) > 1e-9:
                segs.append(physics.Segment(a[0], a[1], b[0], b[1], kind))
    return physics.Track(segs)


def default_start(polys, unit):
    """Above the highest point of the track, sled centred over it."""
    best = None
    for poly in polys:
        pts = poly[1]
        for (u, v) in pts:
            if best is None or v > best[1]:
                best = (u, v)
    if best is None:
        return 0.0, 0.0
    return best[0] - 6.0 * unit, best[1] + 14.0 * unit


# --------------------------------------------------------------------------
# line styles
# --------------------------------------------------------------------------
def ensure_styles(doc):
    """Create the LR line styles if missing. Needs an open transaction.
    Returns {name: GraphicsStyle}."""
    cats = doc.Settings.Categories
    lines = cats.get_Item(BuiltInCategory.OST_Lines)
    existing = {}
    for sc in lines.SubCategories:
        existing[sc.Name] = sc
    out = {}
    for name, rgb, weight, _ in STYLES:
        sc = existing.get(name)
        if sc is None:
            sc = cats.NewSubcategory(lines, name)
            sc.LineColor = Color(rgb[0], rgb[1], rgb[2])
            try:
                sc.SetLineWeight(weight, GraphicsStyleType.Projection)
            except Exception:
                pass
        out[name] = sc.GetGraphicsStyle(GraphicsStyleType.Projection)
    return out


def styles_exist(doc):
    lines = doc.Settings.Categories.get_Item(BuiltInCategory.OST_Lines)
    names = set(sc.Name for sc in lines.SubCategories)
    return all(s[0] in names for s in STYLES)


# --------------------------------------------------------------------------
# demo track
# --------------------------------------------------------------------------
def _overlaps(a, b):
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def draw_demo(doc, view, frame, center_uv, unit, existing_polys=None, old_ids=None):
    """Draws the demo course as detail lines (plus START/JUMP/BOOST/FINISH
    labels) with its start near center_uv, moved aside if other lines are in
    the way. Deletes the previous demo (old_ids) first.
    Returns (start_uv, bbox_uv, count, new_ids). Opens its own transaction."""
    polys = demo.build()
    labels = dict(demo.LABELS)
    xs = [x for _, pts in polys for (x, _) in pts]
    ys = [y for _, pts in polys for (_, y) in pts]
    # rider start (0, 0) a bit left of the visible centre
    u0 = center_uv[0] - 120.0 * unit
    v0 = center_uv[1] + 60.0 * unit

    def bbox_for(u0, v0):
        return (u0 + min(xs) * unit, v0 - max(ys) * unit, u0 + max(xs) * unit, v0 - min(ys) * unit)

    t = Transaction(doc, "Line Rider: demo track")
    t.Start()
    try:
        deleted = 0
        for i in old_ids or []:
            try:
                el = doc.GetElement(ElementId(int(i)))
                if el is not None:
                    doc.Delete(el.Id)
                    deleted += 1
            except Exception:
                pass
        if deleted:
            doc.Regenerate()
        # keep clear of lines that are already in the view
        if existing_polys:
            old = set(int(i) for i in (old_ids or []))
            others = [p for p in existing_polys if len(p) < 3 or p[2] not in old]
            eb = uv_bbox(others) if others else None
            if eb is not None:
                margin = 150.0 * unit
                eb = (eb[0] - margin, eb[1] - margin, eb[2] + margin, eb[3] + margin)
                if _overlaps(bbox_for(u0, v0), eb):
                    # put the course to the right of everything, start at the same height
                    u0 = eb[2] - min(xs) * unit
        gs = ensure_styles(doc)
        ids = []
        count = 0
        for kind, pts in polys:
            style = gs[KIND_STYLE[kind]]
            xyz = [frame.detail_xyz(u0 + x * unit, v0 - y * unit) for (x, y) in pts]
            for p, q in zip(xyz[:-1], xyz[1:]):
                dc = doc.Create.NewDetailCurve(view, Line.CreateBound(p, q))
                dc.LineStyle = style
                ids.append(eid_int(dc.Id))
                count += 1
        # labels
        try:
            ttype = doc.GetDefaultElementTypeId(ElementTypeGroup.TextNoteType)
            labels["START"] = (-20.0, -45.0)
            for text, (x, y) in labels.items():
                note = TextNote.Create(doc, view.Id, frame.detail_xyz(u0 + x * unit, v0 - y * unit), text, ttype)
                ids.append(eid_int(note.Id))
        except Exception as ex:
            settings.log("demo labels: %s" % ex)
        try:
            if view.CropBoxActive:
                view.CropBoxActive = False
        except Exception:
            pass
        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise
    return (u0, v0), bbox_for(u0, v0), count, ids


# --------------------------------------------------------------------------
# picking & view helpers
# --------------------------------------------------------------------------
def pick_point(uidoc, view, prompt):
    """PickPoint that also works in sections/elevations (sets a work plane
    on the view if it has none). Returns XYZ or None if cancelled."""
    sel = uidoc.Selection
    try:
        return sel.PickPoint(prompt)
    except OperationCanceledException:
        return None
    except Exception:
        pass
    doc = uidoc.Document
    t = Transaction(doc, "Line Rider: set work plane")
    t.Start()
    try:
        sp = SketchPlane.Create(doc, Plane.CreateByNormalAndOrigin(view.ViewDirection, view.Origin))
        view.SketchPlane = sp
        t.Commit()
    except Exception:
        t.RollBack()
        raise
    try:
        return sel.PickPoint(prompt)
    except OperationCanceledException:
        return None


def ui_view(uidoc, view):
    for uv in uidoc.GetOpenUIViews():
        if eid_int(uv.ViewId) == eid_int(view.Id):
            return uv
    return None


def visible_center_uv(uidoc, view, frame):
    uiv = ui_view(uidoc, view)
    if uiv is None:
        return 0.0, 0.0
    c = uiv.GetZoomCorners()
    a, b = frame.uv(c[0]), frame.uv(c[1])
    return (a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5


def zoom_to_uv(uidoc, view, frame, bbox, margin=0.08):
    uiv = ui_view(uidoc, view)
    if uiv is None:
        return
    u0, v0, u1, v1 = bbox
    du, dv = (u1 - u0) * margin, (v1 - v0) * margin
    uiv.ZoomAndCenterRectangle(frame.xyz(u0 - du, v0 - dv), frame.xyz(u1 + du, v1 + dv))
