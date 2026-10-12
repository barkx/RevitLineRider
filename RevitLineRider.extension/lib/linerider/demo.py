# -*- coding: utf-8 -*-
"""Demo course, in rider units (y down). The rider starts at (0, 0) facing
right. The layout is validated by tests/check_demo.py: it must finish without a
crash even when the start point is nudged around."""
from __future__ import division
import math

NORMAL, ONEWAY, ACCEL_LINE = 0, 1, 2


def _scurve(x0, y0, x1, y1, n):
    pts = []
    for k in range(n + 1):
        t = k / float(n)
        pts.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * (1 - math.cos(math.pi * t)) * 0.5))
    return pts


def _hill(x0, y0, length, drop, slope0, n=16):
    """Downhill that starts with slope `slope0`, steepens, then flattens out
    (cubic with zero slope at the bottom). Returns points after (x0, y0)."""
    # y(t) = y0 + L*(s0*t + a*t^2 + b*t^3) over t in [0,1]; y'(1)=0, y(1)=y0+drop
    L = float(length)
    d = drop / L
    s0 = slope0
    # s0 + a + b = d (height) and s0 + 2a + 3b = 0 (flat at the bottom)
    a = 3 * d - 2 * s0
    b = s0 - 2 * d
    pts = []
    for k in range(1, n + 1):
        t = k / float(n)
        pts.append((x0 + L * t, y0 + L * (s0 * t + a * t * t + b * t ** 3)))
    return pts


def _kicker(x, y, length, deg, straight, steps=12):
    """Ramp whose slope grows smoothly to `deg`, then a straight lip."""
    ang = math.radians(deg)
    pts = []
    for k in range(1, steps + 1):
        t = k / float(steps)
        a = ang * t * t
        x += math.cos(a) * length / steps
        y -= math.sin(a) * length / steps
        pts.append((x, y))
    x += math.cos(ang) * straight
    y -= math.sin(ang) * straight
    pts.append((x, y))
    return pts


DEFAULTS = dict(drop=110.0, hill_len=260.0, flat1=60.0,
                kick_len=70.0, kick_deg=18.0, kick_straight=25.0,
                gap=110.0, land_below=18.0, land_len=260.0, land_drop=90.0,
                accel_len=120.0, bump_len=300.0, bump_amp=10.0,
                # part 2
                climb1=80.0, climb1_len=400.0,
                table_deg=14.0, table_len=60.0, table_top=180.0,
                table_down=130.0, table_down_len=340.0,
                wave_amp=8.0, wave_len=360.0, waves=2,
                big_drop=70.0, big_len=750.0, big_flat=100.0,
                accel2_len=60.0, bump2_len=450.0, bump2_amp=6.0, bumps2=3,
                # finish
                final_drop=40.0, dip_len=450.0, climb=310.0, climb_len=1100.0, summit=12000.0)

# features, for labels in Revit: name -> (x, y) position (rider units)
LABELS = {}


def _rollers(x, y, length, amp, count, n_per=15):
    pts = []
    n = n_per * count
    for k in range(1, n + 1):
        t = k / float(n)
        pts.append((x + length * t, y - amp * (1 - math.cos(2 * math.pi * count * t)) * 0.5))
    return pts


def build(params=None):
    p = dict(DEFAULTS)
    if params:
        p.update(params)
    LABELS.clear()
    lines = []          # (kind, [(x, y), ...])
    # 1. start: the sled sits just above a slope, so it always gets going
    track = [(-30.0, 0.0), (20.0, 13.0)]
    track += _hill(20.0, 13.0, p["hill_len"], p["drop"], 0.26)
    x, y = track[-1]
    track.append((x + p["flat1"], y))
    x += p["flat1"]
    LABELS["JUMP"] = (x + 40.0, y - 60.0)
    track += _kicker(x, y, p["kick_len"], p["kick_deg"], p["kick_straight"])
    lip_x, lip_y = track[-1]
    lines.append((NORMAL, track))
    # 2. landing: starts after the gap, below the lip, long and smooth
    lx, ly = lip_x + p["gap"], lip_y + p["land_below"]
    land = [(lx - 30.0, ly - 6.0)] + _scurve(lx, ly, lx + p["land_len"], ly + p["land_drop"], 14)
    x, y = land[-1]
    lines.append((NORMAL, land))
    # 3. accelerator strip (drawn left -> right = boost to the right)
    LABELS["BOOST"] = (x + p["accel_len"] * 0.5, y - 40.0)
    lines.append((ACCEL_LINE, [(x, y), (x + p["accel_len"], y)]))
    x += p["accel_len"]
    # 4. rollers
    rest = [(x, y)] + _rollers(x, y, p["bump_len"], p["bump_amp"], 2)
    x, y = rest[-1]
    LABELS["ROLLERS"] = (x - p["bump_len"] * 0.6, y - 50.0)
    # 5. climb, then a tabletop (ramp, flat top, long downslope)
    rest += _scurve(x, y, x + p["climb1_len"], y - p["climb1"], 14)[1:]
    x, y = rest[-1]
    LABELS["TABLETOP"] = (x + 60.0, y - 70.0)
    ramp = _kicker(x, y, p["table_len"], p["table_deg"], 15.0, steps=10)
    rest += ramp
    x, y = rest[-1]
    rest.append((x + p["table_top"], y))
    x += p["table_top"]
    rest += _scurve(x, y, x + p["table_down_len"], y + p["table_down"], 16)[1:]
    x, y = rest[-1]
    # 6. waves
    LABELS["WAVES"] = (x + p["wave_len"] * 0.5, y - 60.0)
    rest += _rollers(x, y, p["wave_len"] * p["waves"], -p["wave_amp"], int(p["waves"]), 18)
    x, y = rest[-1]
    # 7. big drop
    LABELS["BIG DROP"] = (x + 40.0, y - 60.0)
    rest += _hill(x, y, p["big_len"], p["big_drop"], 0.05, 24)
    x, y = rest[-1]
    rest.append((x + p["big_flat"], y))
    x += p["big_flat"]
    lines.append((NORMAL, rest))
    # 8. second booster
    LABELS["BOOST 2"] = (x + p["accel2_len"] * 0.5, y - 40.0)
    lines.append((ACCEL_LINE, [(x, y), (x + p["accel2_len"], y)]))
    x += p["accel2_len"]
    # 9. rollers, dip and the long climb to the finish summit
    rest = [(x, y)] + _rollers(x, y, p["bump2_len"], p["bump2_amp"], int(p["bumps2"]))
    x, y = rest[-1]
    rest += _scurve(x, y, x + p["dip_len"], y + p["final_drop"], 12)[1:]
    x, y = rest[-1]
    rest += _scurve(x, y, x + p["climb_len"], y - p["climb"], 20)[1:]
    x, y = rest[-1]
    # finish: the climb eats the speed, then the rider glides slowly along
    # the summit (about 3 units per frame)
    LABELS["FINISH"] = (x + 30.0, y - 50.0)
    rest.append((x + p["summit"], y))
    lines.append((NORMAL, rest))
    return lines
