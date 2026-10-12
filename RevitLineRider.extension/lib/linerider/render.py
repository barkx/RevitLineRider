# -*- coding: utf-8 -*-
"""DirectContext3D server that draws the rider (and track markers) into one
Revit view. Nothing is ever added to the model."""
import linerider  # noqa: F401
from System import Guid
from Autodesk.Revit.DB import ColorWithTransparency, Outline, XYZ
from Autodesk.Revit.DB.DirectContext3D import (
    DrawContext, EffectInstance, IDirectContext3DServer, IndexBuffer,
    IndexLine, IndexTriangle, PrimitiveType, VertexBuffer, VertexFormat,
    VertexFormatBits, VertexPositionColored)
from Autodesk.Revit.DB.ExternalService import (
    ExternalServiceRegistry, ExternalServices)

from linerider import settings

MAX_PRIMS = 9000   # per buffer (16-bit indices)


def _color(rgb):
    return ColorWithTransparency(int(rgb[0]), int(rgb[1]), int(rgb[2]), 0)


class RiderServer(IDirectContext3DServer):
    def __init__(self, view_id_int):
        self._guid = Guid.NewGuid()
        self.view_id = view_id_int
        self.tris = []      # [(XYZ, XYZ, XYZ, ColorWithTransparency)]
        self.lines = []     # [(XYZ, XYZ, ColorWithTransparency)]
        self.bbox = None    # (XYZ min, XYZ max)
        self.enabled = True
        self._fmt = None
        self._eff = None
        self.errors = 0
        self.calls = 0

    # -- IExternalServer -------------------------------------------------------
    def GetServerId(self):
        return self._guid

    def GetServiceId(self):
        return ExternalServices.BuiltInExternalServices.DirectContext3DService

    def GetName(self):
        return "Revit Line Rider"

    def GetVendorId(self):
        return "LUZ"

    def GetDescription(self):
        return "Draws the Line Rider sled in the active view"

    # -- IDirectContext3DServer --------------------------------------------------
    def GetApplicationId(self):
        return ""

    def GetSourceId(self):
        return ""

    def UsesHandles(self):
        return False

    def UseInTransparentPass(self, view):
        return False

    def CanExecute(self, view):
        try:
            vid = view.Id
            try:
                v = vid.Value
            except AttributeError:
                v = vid.IntegerValue
            return self.enabled and v == self.view_id
        except Exception:
            return False

    def GetBoundingBox(self, view):
        if self.bbox is None:
            return None
        return Outline(self.bbox[0], self.bbox[1])

    def RenderScene(self, view, display_style):
        try:
            if not self.enabled:
                return
            self.calls += 1
            if self._fmt is None:
                self._fmt = VertexFormat(VertexFormatBits.PositionColored)
                self._eff = EffectInstance(VertexFormatBits.PositionColored)
            tris = self.tris
            lines = self.lines
            for k in range(0, len(tris), MAX_PRIMS):
                self._flush_tris(tris[k:k + MAX_PRIMS])
            for k in range(0, len(lines), MAX_PRIMS):
                self._flush_lines(lines[k:k + MAX_PRIMS])
        except Exception as ex:
            self.errors += 1
            if self.errors < 5:
                settings.log("RenderScene error: %s" % ex)

    # -- buffers -------------------------------------------------------------
    def _flush_tris(self, tris):
        if not tris:
            return
        n_tri = len(tris) * 2              # both windings: never culled
        n_vert = len(tris) * 3
        vsize = VertexPositionColored.GetSizeInFloats() * n_vert
        vb = VertexBuffer(vsize)
        vb.Map(vsize)
        vs = vb.GetVertexStreamPositionColored()
        for (a, b, c, col) in tris:
            vs.AddVertex(VertexPositionColored(a, col))
            vs.AddVertex(VertexPositionColored(b, col))
            vs.AddVertex(VertexPositionColored(c, col))
        vb.Unmap()
        isize = IndexTriangle.GetSizeInShortInts() * n_tri
        ib = IndexBuffer(isize)
        ib.Map(isize)
        st = ib.GetIndexStreamTriangle()
        for k in range(len(tris)):
            i = 3 * k
            st.AddTriangle(IndexTriangle(i, i + 1, i + 2))
            st.AddTriangle(IndexTriangle(i, i + 2, i + 1))
        ib.Unmap()
        DrawContext.FlushBuffer(vb, n_vert, ib, isize, self._fmt, self._eff,
                                PrimitiveType.TriangleList, 0, n_tri)

    def _flush_lines(self, lines):
        if not lines:
            return
        n_vert = len(lines) * 2
        vsize = VertexPositionColored.GetSizeInFloats() * n_vert
        vb = VertexBuffer(vsize)
        vb.Map(vsize)
        vs = vb.GetVertexStreamPositionColored()
        for (a, b, col) in lines:
            vs.AddVertex(VertexPositionColored(a, col))
            vs.AddVertex(VertexPositionColored(b, col))
        vb.Unmap()
        isize = IndexLine.GetSizeInShortInts() * len(lines)
        ib = IndexBuffer(isize)
        ib.Map(isize)
        st = ib.GetIndexStreamLine()
        for k in range(len(lines)):
            st.AddLine(IndexLine(2 * k, 2 * k + 1))
        ib.Unmap()
        DrawContext.FlushBuffer(vb, n_vert, ib, isize, self._fmt, self._eff,
                                PrimitiveType.LineList, 0, len(lines))


def _service():
    return ExternalServiceRegistry.GetService(
        ExternalServices.BuiltInExternalServices.DirectContext3DService)


def register(server):
    service = _service()
    service.AddServer(server)
    ids = service.GetActiveServerIds()
    ids.Add(server.GetServerId())
    service.SetActiveServers(ids)


def unregister(server):
    try:
        server.enabled = False
        _service().RemoveServer(server.GetServerId())
    except Exception as ex:
        settings.log("unregister: %s" % ex)


color = _color
