# -*- coding: utf-8 -*-
"""Ride the lines in the active view."""
__persistentengine__ = True
__title__ = "Ride"
__author__ = "LUZ Team"

import linerider
linerider.fresh()   # always run the code that is on disk
from linerider import game

game.launch(__revit__)  # noqa: F821
