# -*- coding: utf-8 -*-
"""Line Rider physics, pure Python (IronPython 2.7 / 3.4 and CPython).

Coordinates are "rider units" with Y pointing DOWN, like the original game.
The sled is 17.5 units long. The Revit side converts feet <-> units.

Model (after the classic Line Rider engine):
  * 10 contact points integrated with Verlet (position + previous position)
  * sticks ("bones") solved 6 times per frame, interleaved with line collisions
  * mount bones break when stretched too far -> the rider crashes off the sled
  * 40 frames per second, gravity 0.175 units/frame^2
"""
from __future__ import division
import math

FPS = 40.0
GRAVITY = 0.175
ITERATIONS = 6
HITBOX = 10.0          # how deep a point may sink into a one-way line and still be caught
ENDURANCE = 0.057      # mount bone strength
START_VEL = 0.4        # units / frame to the right
ACCEL = 0.1            # boost per contact per iteration on acceleration lines
CELL = 14.0            # spatial grid cell size
EXT = 0.5              # every line is extended by this many units at each end
EPS = 1e-4
MEMORY_FRAMES = 20     # how long a point remembers which side of a line chain it is on

# line kinds
NORMAL, ONEWAY, ACCEL_LINE = 0, 1, 2

PEG, TAIL, NOSE, STRING, BUTT, SHOULDER, RHAND, LHAND, LFOOT, RFOOT = range(10)
POINT_NAMES = ["peg", "tail", "nose", "string", "butt", "shoulder",
               "rhand", "lhand", "lfoot", "rfoot"]
#            x      y    friction
POINTS = [(0.0,   0.0, 0.8),   # peg (back of sled seat)
          (0.0,   5.0, 0.0),   # tail
          (15.0,  5.0, 0.0),   # nose
          (17.5,  0.0, 0.0),   # string (front curl)
          (5.0,   0.0, 0.8),   # butt
          (5.0,  -5.5, 0.8),   # shoulder
          (11.5, -5.0, 0.1),   # right hand
          (11.5, -5.0, 0.1),   # left hand
          (10.0,  5.0, 0.0),   # left foot
          (10.0,  5.0, 0.0)]   # right foot

SLED_BONES = [(PEG, TAIL), (TAIL, NOSE), (NOSE, STRING), (STRING, PEG),
              (PEG, NOSE), (STRING, TAIL)]
MOUNT_BONES = [(PEG, BUTT), (TAIL, BUTT), (NOSE, BUTT), (SHOULDER, PEG),
               (STRING, LHAND), (STRING, RHAND), (LFOOT, NOSE), (RFOOT, NOSE)]
BODY_BONES = [(SHOULDER, BUTT), (SHOULDER, LHAND), (SHOULDER, RHAND),
              (BUTT, LFOOT), (BUTT, RFOOT)]
REPEL_BONES = [(SHOULDER, LFOOT), (SHOULDER, RFOOT)]

SCARF_LEN = 7
SCARF_SEG = 2.0
SCARF_DRAG = 0.9


# --------------------------------------------------------------------------
# Track
# --------------------------------------------------------------------------
class Segment(object):
    __slots__ = ("ax", "ay", "bx", "by", "kind", "tx", "ty", "nx", "ny",
                 "length", "lo", "hi", "tag", "chain", "cflip")

    def __init__(self, ax, ay, bx, by, kind=NORMAL, tag=None):
        self.ax, self.ay, self.bx, self.by = ax, ay, bx, by
        self.kind = kind
        self.tag = tag
        self.chain = -1
        self.cflip = 1
        dx, dy = bx - ax, by - ay
        L = math.sqrt(dx * dx + dy * dy) or 1e-12
        self.length = L
        self.tx, self.ty = dx / L, dy / L
        # normal pointing INTO the line from its riding side.
        # Drawn left->right (y down) => riding side is on top, normal = (0, +1)
        self.nx, self.ny = -self.ty, self.tx
        e = min(EXT, L * 0.25)
        self.lo = -e
        self.hi = L + e


class Track(object):
    def __init__(self, segments=None):
        self.segments = []
        self.grid = {}
        self.bbox = None
        for s in segments or []:
            self.add(s)
        self.build_chains()

    def build_chains(self):
        """Group segments that share end points into chains with a consistent
        normal orientation, so a point riding over a joint keeps its side."""
        def key(x, y):
            return (int(round(x * 100.0)), int(round(y * 100.0)))
        ends = {}
        for i, s in enumerate(self.segments):
            s.chain = -1
            ends.setdefault(key(s.ax, s.ay), []).append((i, 0))
            ends.setdefault(key(s.bx, s.by), []).append((i, 1))
        segs = self.segments
        chain = 0
        for i0 in range(len(segs)):
            if segs[i0].chain >= 0:
                continue
            segs[i0].chain, segs[i0].cflip = chain, 1
            stack = [i0]
            while stack:
                i = stack.pop()
                s = segs[i]
                for end, (x, y) in ((0, (s.ax, s.ay)), (1, (s.bx, s.by))):
                    for (j, jend) in ends.get(key(x, y), ()):
                        if j == i or segs[j].chain >= 0:
                            continue
                        # consecutive (end->start) keeps orientation, else flip
                        segs[j].chain = chain
                        segs[j].cflip = s.cflip if end != jend else -s.cflip
                        stack.append(j)
            chain += 1

    def add(self, seg):
        if seg.length < 1e-6:
            return
        idx = len(self.segments)
        self.segments.append(seg)
        cells = set()
        n = int(seg.length / (CELL * 0.5)) + 1
        for k in range(n + 1):
            f = k / float(n)
            x = seg.ax + (seg.bx - seg.ax) * f
            y = seg.ay + (seg.by - seg.ay) * f
            cx, cy = int(math.floor(x / CELL)), int(math.floor(y / CELL))
            for i in (-1, 0, 1):
                for j in (-1, 0, 1):
                    cells.add((cx + i, cy + j))
        for c in cells:
            lst = self.grid.get(c)
            if lst is None:
                self.grid[c] = [idx]
            else:
                lst.append(idx)
        xs = (seg.ax, seg.bx)
        ys = (seg.ay, seg.by)
        if self.bbox is None:
            self.bbox = [min(xs), min(ys), max(xs), max(ys)]
        else:
            b = self.bbox
            b[0] = min(b[0], min(xs)); b[1] = min(b[1], min(ys))
            b[2] = max(b[2], max(xs)); b[3] = max(b[3], max(ys))

    def candidates(self, x, y, px, py):
        """Segments near (x,y); also sweeps from previous position for fast points."""
        grid = self.grid
        cx, cy = int(math.floor(x / CELL)), int(math.floor(y / CELL))
        dx, dy = x - px, y - py
        d2 = dx * dx + dy * dy
        if d2 < (CELL * 0.5) ** 2:
            return grid.get((cx, cy), ())
        out = set()
        n = int(math.sqrt(d2) / (CELL * 0.5)) + 1
        for k in range(n + 1):
            f = k / float(n)
            c = (int(math.floor((px + dx * f) / CELL)),
                 int(math.floor((py + dy * f) / CELL)))
            lst = grid.get(c)
            if lst:
                out.update(lst)
        return out


# --------------------------------------------------------------------------
# Rider
# --------------------------------------------------------------------------
class Rider(object):
    def __init__(self, x=0.0, y=0.0, direction=1, vel=START_VEL):
        d = 1 if direction >= 0 else -1
        self.direction = d
        self.pos = []
        self.prev = []
        self.fric = []
        for (px, py, fr) in POINTS:
            X, Y = x + px * d, y + py
            self.pos.append([X, Y])
            self.prev.append([X - vel * d, Y])
            self.fric.append(fr)
        self.bones = []      # (a, b, rest, kind) kind 0 normal 1 mount 2 repel
        for (a, b) in SLED_BONES + BODY_BONES:
            self.bones.append((a, b, self._dist(a, b), 0))
        for (a, b) in MOUNT_BONES:
            self.bones.append((a, b, self._dist(a, b), 1))
        for (a, b) in REPEL_BONES:
            self.bones.append((a, b, self._dist(a, b) * 0.5, 2))
        self.crashed = False
        self.crash_frame = None
        self.crash_reason = ""
        self.sled_sign = self._sled_cross() >= 0
        sx, sy = self.pos[SHOULDER]
        self.scarf = [[sx - (i + 1) * SCARF_SEG * d, sy] for i in range(SCARF_LEN)]
        self.scarf_prev = [[p[0] - vel * d, p[1]] for p in self.scarf]
        self.frame = 0
        self.contacts = 0
        self.mem = [dict() for _ in range(len(self.pos))]

    def _dist(self, a, b):
        ax, ay = self.pos[a]
        bx, by = self.pos[b]
        return math.sqrt((ax - bx) ** 2 + (ay - by) ** 2)

    def _sled_cross(self):
        tx, ty = self.pos[TAIL]
        nx, ny = self.pos[NOSE]
        sx, sy = self.pos[STRING]
        return (nx - tx) * (sy - ty) - (ny - ty) * (sx - tx)

    # -- state copy (flags) ------------------------------------------------
    def snapshot(self):
        return {
            "pos": [list(p) for p in self.pos],
            "prev": [list(p) for p in self.prev],
            "crashed": self.crashed, "crash_frame": self.crash_frame,
            "scarf": [list(p) for p in self.scarf],
            "scarf_prev": [list(p) for p in self.scarf_prev],
            "frame": self.frame,
            "mem": [dict(m) for m in self.mem],
        }

    def restore(self, s):
        self.pos = [list(p) for p in s["pos"]]
        self.prev = [list(p) for p in s["prev"]]
        self.crashed = s["crashed"]
        self.crash_frame = s["crash_frame"]
        self.scarf = [list(p) for p in s["scarf"]]
        self.scarf_prev = [list(p) for p in s["scarf_prev"]]
        self.frame = s["frame"]
        self.mem = [dict(m) for m in s["mem"]]

    # -- queries -------------------------------------------------------------
    def center(self):
        bx, by = self.pos[BUTT]
        sx, sy = self.pos[SHOULDER]
        return (bx + sx) * 0.5, (by + sy) * 0.5

    def speed(self):
        """units per frame (sled peg)"""
        p, q = self.pos[BUTT], self.prev[BUTT]
        return math.sqrt((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2)

    # -- simulation ------------------------------------------------------------
    def step(self, track):
        pos, prev = self.pos, self.prev
        # 1. momentum + gravity
        for i in range(len(pos)):
            p, q = pos[i], prev[i]
            vx, vy = p[0] - q[0], p[1] - q[1]
            q[0], q[1] = p[0], p[1]
            p[0] += vx
            p[1] += vy + GRAVITY
        # 2. constraints + collisions
        self.contacts = 0
        for _ in range(ITERATIONS):
            self._bones()
            for i in range(len(pos)):
                self._collide(i, track)
        # 3. sled flipped upside down -> crash
        if not self.crashed and (self._sled_cross() >= 0) != self.sled_sign:
            self._crash("sled flipped")
        self._scarf()
        self.frame += 1

    def _crash(self, why=""):
        if not self.crashed:
            self.crashed = True
            self.crash_frame = self.frame
            self.crash_reason = why

    def _bones(self):
        pos = self.pos
        for (a, b, rest, kind) in self.bones:
            if kind == 1 and self.crashed:
                continue
            pa, pb = pos[a], pos[b]
            dx, dy = pa[0] - pb[0], pa[1] - pb[1]
            L = math.sqrt(dx * dx + dy * dy)
            if L == 0.0:
                continue
            if kind == 2 and L >= rest:
                continue
            diff = (L - rest) / L * 0.5
            if kind == 1 and diff > ENDURANCE * rest * 0.5:
                self._crash("%s-%s" % (POINT_NAMES[a], POINT_NAMES[b]))
                continue
            ox, oy = dx * diff, dy * diff
            pa[0] -= ox; pa[1] -= oy
            pb[0] += ox; pb[1] += oy

    def _collide(self, i, track):
        p, q = self.pos[i], self.prev[i]
        fr = self.fric[i]
        segs = track.segments
        mem = self.mem[i]
        frame = self.frame
        for si in track.candidates(p[0], p[1], q[0], q[1]):
            s = segs[si]
            x, y = p[0], p[1]
            vx, vy = x - q[0], y - q[1]
            rx, ry = x - s.ax, y - s.ay
            nx, ny = s.nx, s.ny
            rel = rx * nx + ry * ny
            # The riding side is remembered per chain for MEMORY_FRAMES
            # frames (so joints between segments are seamless); otherwise
            # the motion q -> p has to cross the segment itself.
            relq = (q[0] - s.ax) * nx + (q[1] - s.ay) * ny
            m = mem.get(s.chain) if s.chain >= 0 else None
            if m is not None and frame - m[1] <= MEMORY_FRAMES:
                side = m[0] * s.cflip
                along = rx * s.tx + ry * s.ty
                if along < s.lo or along > s.hi:
                    continue
                if side > 0:
                    nx, ny, rel = -nx, -ny, -rel
                if rel <= 0.0 or rel >= HITBOX:
                    continue
                if vx * nx + vy * ny <= 0.0:
                    continue
            else:
                if relq < 0.0:
                    side = -1
                    if rel <= 0.0:
                        continue
                elif relq > 0.0:
                    side = 1
                    if rel >= 0.0:
                        continue
                    nx, ny, rel = -nx, -ny, -rel
                else:
                    continue
                f = abs(relq) / (abs(relq) + rel)
                cx = q[0] + vx * f - s.ax
                cy = q[1] + vy * f - s.ay
                along = cx * s.tx + cy * s.ty
                if along < -0.05 or along > s.length + 0.05:
                    continue
            if s.kind == ONEWAY and side > 0:
                continue        # one-way lines only collide from their riding side
            if s.chain >= 0:
                mem[s.chain] = (side * s.cflip, frame)
            # push back onto the line surface (a hair on the riding side)
            push = rel + EPS
            p[0] = x - nx * push
            p[1] = y - ny * push
            self.contacts += 1
            # friction: slow the tangential velocity
            vt = vx * s.tx + vy * s.ty
            if fr > 0.0 and vt != 0.0:
                f = min(fr * rel, abs(vt))
                if vt < 0:
                    f = -f
                q[0] += s.tx * f
                q[1] += s.ty * f
            if s.kind == ACCEL_LINE:
                q[0] -= s.tx * ACCEL
                q[1] -= s.ty * ACCEL

    def _scarf(self):
        sx, sy = self.pos[SHOULDER]
        for i in range(SCARF_LEN):
            p, q = self.scarf[i], self.scarf_prev[i]
            vx, vy = (p[0] - q[0]) * SCARF_DRAG, (p[1] - q[1]) * SCARF_DRAG
            q[0], q[1] = p[0], p[1]
            p[0] += vx
            p[1] += vy + GRAVITY * 0.5
        ax, ay = sx, sy
        for i in range(SCARF_LEN):
            p = self.scarf[i]
            dx, dy = p[0] - ax, p[1] - ay
            L = math.sqrt(dx * dx + dy * dy) or 1e-9
            k = SCARF_SEG / L
            p[0], p[1] = ax + dx * k, ay + dy * k
            ax, ay = p[0], p[1]


# --------------------------------------------------------------------------
# Drawing primitives (shared by the Revit renderer and the preview tool)
# --------------------------------------------------------------------------
COLORS = {
    "sled": (139, 90, 43),
    "sled_dark": (92, 56, 24),
    "rope": (60, 60, 60),
    "coat": (46, 90, 172),
    "legs": (40, 40, 48),
    "skin": (242, 201, 160),
    "hat": (30, 30, 36),
    "scarf_a": (208, 49, 45),
    "scarf_b": (250, 250, 250),
    "outline": (20, 20, 20),
}


def _quad(a, b, w):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L = math.sqrt(dx * dx + dy * dy) or 1e-9
    nx, ny = -dy / L * w * 0.5, dx / L * w * 0.5
    p1, p2 = (ax + nx, ay + ny), (bx + nx, by + ny)
    p3, p4 = (bx - nx, by - ny), (ax - nx, ay - ny)
    return [(p1, p2, p3), (p1, p3, p4)]


def _disc(c, r, n=14):
    tris = []
    pts = [(c[0] + r * math.cos(2 * math.pi * k / n),
            c[1] + r * math.sin(2 * math.pi * k / n)) for k in range(n)]
    for k in range(n):
        tris.append((c, pts[k], pts[(k + 1) % n]))
    return tris, pts


def rider_shapes(r):
    """Returns (triangles, lines) in rider units.
    triangles: list of (layer, color, (p1,p2,p3)); lines: list of (layer, color, p1, p2)."""
    P = r.pos
    tris, lines = [], []

    def T(layer, col, shapes):
        for t in shapes:
            tris.append((layer, COLORS[col], t))

    def Lp(layer, col, pts, closed=False):
        n = len(pts)
        rng = range(n if closed else n - 1)
        for k in rng:
            lines.append((layer, COLORS[col], pts[k], pts[(k + 1) % n]))

    peg, tail, nose, strg = P[PEG], P[TAIL], P[NOSE], P[STRING]
    butt, sh = P[BUTT], P[SHOULDER]
    # scarf (behind)
    chain = [tuple(sh)] + [tuple(p) for p in r.scarf]
    for k in range(len(chain) - 1):
        T(0, "scarf_a" if k % 2 == 0 else "scarf_b", _quad(chain[k], chain[k + 1], 1.4))
    # sled
    T(1, "sled", _quad(tail, nose, 1.1))
    T(1, "sled", _quad(nose, strg, 1.1))
    T(1, "sled_dark", _quad(peg, tail, 0.8))
    T(1, "sled_dark", _quad(peg, strg, 0.6))
    Lp(5, "outline", [tuple(peg), tuple(tail), tuple(nose), tuple(strg)])
    # rope
    if not r.crashed:
        lines.append((5, COLORS["rope"], tuple(strg), tuple(P[LHAND])))
        lines.append((5, COLORS["rope"], tuple(strg), tuple(P[RHAND])))
    # legs
    T(2, "legs", _quad(butt, P[LFOOT], 1.5))
    T(2, "legs", _quad(butt, P[RFOOT], 1.5))
    # torso
    T(3, "coat", _quad(butt, sh, 3.0))
    # arms
    T(4, "coat", _quad(sh, P[LHAND], 1.1))
    T(4, "coat", _quad(sh, P[RHAND], 1.1))
    # head
    dx, dy = sh[0] - butt[0], sh[1] - butt[1]
    L = math.sqrt(dx * dx + dy * dy) or 1e-9
    ux, uy = dx / L, dy / L
    hc = (sh[0] + ux * 2.6, sh[1] + uy * 2.6)
    dt, ring = _disc(hc, 2.2)
    T(4, "skin", dt)
    Lp(5, "outline", ring, closed=True)
    # hat
    hb = (hc[0] + ux * 1.0, hc[1] + uy * 1.0)
    ht = (hc[0] + ux * 3.2, hc[1] + uy * 3.2)
    T(5, "hat", _quad(hb, ht, 3.4))
    # outlines of the body
    Lp(5, "outline", [tuple(butt), tuple(sh)])
    return tris, lines


def _under_a_line(track, x, y, reach=12.0):
    """True if a line passes within `reach` units straight above (x, y),
    i.e. the point would start inside or under a line."""
    for si in track.candidates(x, y - reach * 0.5, x, y - reach * 0.5):
        s = track.segments[si]
        x0, x1 = (s.ax, s.bx) if s.ax <= s.bx else (s.bx, s.ax)
        if x1 - x0 < 1e-9 or not (x0 <= x <= x1):
            continue
        ly = s.ay + (s.by - s.ay) * (x - s.ax) / (s.bx - s.ax)
        if 0.0 <= y - ly <= reach:
            return True
    return False


def safe_start(track, x=0.0, y=0.0, direction=1, max_lift=80.0):
    """Start position for the rider at (x, y), lifted up (in 0.5 unit steps)
    until no contact point starts inside or just under a line. A start point
    clicked right on a line then puts the sled on top of it."""
    d = 1 if direction >= 0 else -1
    lift = 0.0
    while lift <= max_lift:
        yy = y - lift
        if not any(_under_a_line(track, x + px * d, yy + py) for (px, py, _) in POINTS):
            return x, yy
        lift += 0.5
    return x, y
