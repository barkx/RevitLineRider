# -*- coding: utf-8 -*-
"""The game session: HUD window, ExternalEvent game loop, camera follow."""
from __future__ import division
import math
import traceback

import linerider  # noqa: F401
import System
from System import Action, AppDomain, TimeSpan
from System.Diagnostics import Stopwatch
from System.Windows import Visibility, WindowStartupLocation, SystemParameters
from System.Windows.Input import Key, Keyboard, ModifierKeys
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Threading import DispatcherTimer, DispatcherPriority
from System.Windows.Media import SolidColorBrush, Color

from Autodesk.Revit.DB import XYZ
from Autodesk.Revit.UI import ExternalEvent, IExternalEventHandler, TaskDialog

from linerider import physics, render, revitio, settings

KEY = "RevitLineRider.session"
HISTORY_EVERY = 10          # frames between rewind snapshots
MAX_STEPS_PER_TICK = 12
VIEW_UNITS = 360.0           # rider units visible vertically when the camera frames the rider
LAYER_LIFT = 0.006          # ft towards the viewer per drawing layer (max 8 layers)

HUD_XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Line Rider" Width="304" SizeToContent="Height"
        WindowStyle="None" ResizeMode="NoResize" AllowsTransparency="True"
        Background="Transparent" ShowInTaskbar="False" ShowActivated="True"
        FontFamily="Segoe UI" Foreground="#E8ECF1">
  <Window.Resources>
    <Style TargetType="Button">
      <Setter Property="Foreground" Value="#E8ECF1"/>
      <Setter Property="Background" Value="#2C333C"/>
      <Setter Property="BorderBrush" Value="#3B444F"/>
      <Setter Property="Focusable" Value="False"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Height" Value="34"/>
      <Setter Property="Margin" Value="2"/>
      <Setter Property="FontSize" Value="13"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="b" CornerRadius="6" Background="{TemplateBinding Background}"
                    BorderBrush="{TemplateBinding BorderBrush}" BorderThickness="1">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="b" Property="Background" Value="#3A434E"/>
              </Trigger>
              <Trigger Property="IsPressed" Value="True">
                <Setter TargetName="b" Property="Background" Value="#1F6FEB"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style TargetType="RadioButton">
      <Setter Property="Focusable" Value="False"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Margin" Value="2"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="RadioButton">
            <Border x:Name="b" CornerRadius="5" Background="#2C333C" Padding="0,4">
              <TextBlock Text="{TemplateBinding Content}" HorizontalAlignment="Center"
                         Foreground="#C9D1D9" FontSize="12"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsChecked" Value="True">
                <Setter TargetName="b" Property="Background" Value="#1F6FEB"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style TargetType="CheckBox">
      <Setter Property="Focusable" Value="False"/>
      <Setter Property="Foreground" Value="#C9D1D9"/>
      <Setter Property="Margin" Value="0,3,10,3"/>
      <Setter Property="FontSize" Value="12"/>
    </Style>
  </Window.Resources>
  <Border CornerRadius="12" Background="#F0161B22" BorderBrush="#40FFFFFF" BorderThickness="1" Padding="14,10,14,12">
    <StackPanel>
      <DockPanel x:Name="TitleBar" Background="Transparent" Cursor="SizeAll">
        <Button x:Name="BtnClose" DockPanel.Dock="Right" Content="&#x2715;" Width="26" Height="24"
                FontSize="11" Background="Transparent" BorderBrush="Transparent" ToolTip="Quit (restores the view)"/>
        <StackPanel Orientation="Horizontal" VerticalAlignment="Center">
          <Path Data="M0,9 L14,9 L17,5 M2,9 L2,12 L15,12 L18,8" Stroke="#4FA3FF" StrokeThickness="2" Margin="0,0,8,0" VerticalAlignment="Center"/>
          <TextBlock Text="LINE RIDER" FontWeight="Bold" FontSize="14" VerticalAlignment="Center"/>
          <TextBlock Text=" for Revit" FontSize="12" Foreground="#8B949E" VerticalAlignment="Center"/>
        </StackPanel>
      </DockPanel>
      <TextBlock x:Name="TxtView" Text="" Foreground="#8B949E" FontSize="11" Margin="0,2,0,8" TextTrimming="CharacterEllipsis"/>
      <Grid Margin="0,0,0,2">
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="*"/>
          <ColumnDefinition Width="Auto"/>
        </Grid.ColumnDefinitions>
        <TextBlock x:Name="TxtTime" Text="0:00.00" FontSize="30" FontWeight="SemiBold" FontFamily="Consolas"/>
        <StackPanel Grid.Column="1" HorizontalAlignment="Right" VerticalAlignment="Bottom" Margin="0,0,0,4">
          <TextBlock x:Name="TxtSpeed" Text="0 km/h" FontSize="15" FontFamily="Consolas" HorizontalAlignment="Right"/>
          <TextBlock x:Name="TxtFrame" Text="frame 0" FontSize="10" Foreground="#8B949E" HorizontalAlignment="Right"/>
        </StackPanel>
      </Grid>
      <Border x:Name="StatusBox" CornerRadius="5" Background="#253040" Padding="8,4" Margin="0,2,0,8">
        <TextBlock x:Name="TxtStatus" Text="READY" FontWeight="Bold" FontSize="12" TextWrapping="Wrap"/>
      </Border>
      <UniformGrid Columns="4">
        <Button x:Name="BtnPlay" ToolTip="Play / pause (Space)">
          <TextBlock x:Name="TxtPlay" Text="&#x25B6;" FontFamily="Segoe UI Symbol" FontSize="15"/>
        </Button>
        <Button x:Name="BtnReset" ToolTip="Back to start or flag (R). Shift+R ignores the flag.">
          <TextBlock Text="&#x23EE;" FontFamily="Segoe UI Symbol" FontSize="15"/>
        </Button>
        <Button x:Name="BtnFlag" ToolTip="Place a flag here: Reset returns to it (F). Shift+F removes it.">
          <TextBlock Text="&#x2691;" FontFamily="Segoe UI Symbol" FontSize="15"/>
        </Button>
        <Button x:Name="BtnStart" ToolTip="Click a new start point in the view (S)">
          <TextBlock Text="&#x2316;" FontFamily="Segoe UI Symbol" FontSize="15"/>
        </Button>
      </UniformGrid>
      <UniformGrid Columns="4" Margin="0,4,0,0">
        <RadioButton x:Name="Spd1" Content="0.25&#xD7;" GroupName="spd"/>
        <RadioButton x:Name="Spd2" Content="0.5&#xD7;" GroupName="spd"/>
        <RadioButton x:Name="Spd3" Content="1&#xD7;" GroupName="spd"/>
        <RadioButton x:Name="Spd4" Content="2&#xD7;" GroupName="spd"/>
      </UniformGrid>
      <WrapPanel Margin="0,8,0,0">
        <CheckBox x:Name="ChkFollow" Content="Follow camera (C)"/>
        <CheckBox x:Name="ChkLeft" Content="Ride left"/>
      </WrapPanel>
      <Grid Margin="0,4,0,0">
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="*"/>
          <ColumnDefinition Width="40"/>
        </Grid.ColumnDefinitions>
        <TextBlock Text="Rider size" Foreground="#C9D1D9" FontSize="12" VerticalAlignment="Center" Margin="0,0,8,0"/>
        <Slider x:Name="SldSize" Grid.Column="1" Minimum="-2" Maximum="3" Value="0" Focusable="False"
                VerticalAlignment="Center" TickFrequency="0.5" IsSnapToTickEnabled="True"/>
        <TextBlock x:Name="TxtSize" Grid.Column="2" Text="&#xD7;1" Foreground="#C9D1D9" FontSize="12" HorizontalAlignment="Right" VerticalAlignment="Center"/>
      </Grid>
      <Button x:Name="BtnReload" Content="&#x21BB;  Reload track from view" Margin="2,8,2,2" Height="30" FontSize="12"/>
      <TextBlock x:Name="TxtHint" Foreground="#6E7681" FontSize="10.5" TextWrapping="Wrap" Margin="2,8,2,0"
                 Text="Space play/pause &#xB7; R reset &#xB7; F flag &#xB7; &#x2190;/&#x2192; rewind / step &#xB7; 1-4 speed &#xB7; C camera &#xB7; Esc pause. Click this panel first so it gets the keys."/>
    </StackPanel>
  </Border>
</Window>
"""


class _Handler(IExternalEventHandler):
    def __init__(self, game):
        self.game = game

    def Execute(self, uiapp):
        self.game.pending = False
        try:
            self.game.tick(uiapp)
        except Exception:
            settings.log("tick error:\n" + traceback.format_exc())
            self.game.fail(traceback.format_exc())

    def GetName(self):
        return "Revit Line Rider"


def _fmt_time(frames):
    s = frames / physics.FPS
    m = int(s // 60)
    return "%d:%05.2f" % (m, s - m * 60)


class Game(object):
    def __init__(self, uiapp, start=None, unit=None):
        # start/unit passed in (e.g. by Demo Track) win over settings.json, and
        # are written back to it so Reset / Reload keep using them
        self.override_start = start
        self.override_unit = unit
        self.uiapp = uiapp
        self.uidoc = uiapp.ActiveUIDocument
        self.doc = self.uidoc.Document
        self.view = self.uidoc.ActiveView
        self.view_id = revitio.eid_int(self.view.Id)
        self.frame_ = revitio.ViewFrame(self.doc, self.view)
        self.cfg = settings.load()
        self.speed = float(self.cfg.get("speed", 1.0))
        self.follow = bool(self.cfg.get("follow", True))
        self.direction = -1 if self.cfg.get("left") else 1
        self.size = float(self.cfg.get("size", 1.0))
        self.playing = False
        self.dirty = True
        self.closing = False
        self.closed = False
        self.pending = False
        self.actions = []
        self.flag = None
        self.history = {}
        self.acc = 0.0
        self.watch = Stopwatch()
        self.status = "READY"
        self.polys = []
        self.track = None
        self.rider = None
        self.server = None
        self.event = None
        self.hud = None
        self.timer = None
        self.static_tris = []
        self.static_lines = []

    # ------------------------------------------------------------------ setup
    def start(self):
        self.load_track()
        if not self.polys:
            TaskDialog.Show("Line Rider",
                            "There are no lines in this view to ride on.\n\n"
                            "Draw some detail lines (Annotate > Detail Line) or model lines, "
                            "or click 'Demo Track' on the Line Rider tab.")
            return False
        self.server = render.RiderServer(self.view_id)
        render.register(self.server)
        self.event = ExternalEvent.Create(_Handler(self))
        self.reset(use_flag=False)
        self._build_hud()
        AppDomain.CurrentDomain.SetData(KEY, Action(self.close_now))
        AppDomain.CurrentDomain.SetData("RevitLineRider.reload", Action(self.request_reload))
        self.update_geometry()
        try:
            self.zoom_to_rider(self.uidoc, force=False)
        except Exception:
            settings.log("zoom: " + traceback.format_exc())
        self.uidoc.RefreshActiveView()
        settings.log("session started in view %s: %d lines, %d segments, unit %.4f ft, start (%.2f, %.2f)%s"
                     % (self.view.Name, len(self.polys), len(self.track.segments), self.unit,
                        self.u0, self.v0, " (default)" if self.start_is_default else ""))
        return True

    def view_record(self):
        return settings.get_view(self.doc, self.view)

    def load_track(self):
        self.polys = revitio.read_track_uv(self.doc, self.view, self.frame_)
        rec = dict(self.view_record())
        if self.override_unit:
            rec["unit"] = self.override_unit
        if self.override_start:
            rec["start"] = list(self.override_start)
        unit = rec.get("unit")
        if not unit:
            unit = revitio.default_unit(self.view)
            bb = revitio.uv_bbox(self.polys)
            if bb:
                span = max(bb[2] - bb[0], bb[3] - bb[1])
                # keep tracks in a playable size range (in rider units)
                if span / unit > 9000:
                    unit = span / 9000.0
                elif span / unit < 120:
                    unit = span / 120.0
        self.base_unit = unit
        self.unit = unit * self.size
        start = rec.get("start")
        if start:
            self.u0, self.v0 = start[0], start[1]
            self.start_is_default = False
        else:
            self.u0, self.v0 = revitio.default_start(self.polys, self.unit)
            self.start_is_default = True
        self.track = revitio.build_track(self.polys, self.u0, self.v0, self.unit)
        self.build_static()

    def reset(self, use_flag=True):
        if use_flag and self.flag is not None:
            self.rider.restore(self.flag)
        else:
            sx, sy = physics.safe_start(self.track, 0.0, 0.0, self.direction)
            self.rider = physics.Rider(sx, sy, self.direction)
        self.history = {}
        self.history[self.rider.frame] = self.rider.snapshot()
        self.acc = 0.0
        self.dirty = True

    # --------------------------------------------------------------- the HUD
    def _build_hud(self):
        w = XamlReader.Parse(HUD_XAML)
        self.hud = w
        f = w.FindName
        self.ui = dict((n, f(n)) for n in (
            "TitleBar", "BtnClose", "TxtView", "TxtTime", "TxtSpeed", "TxtFrame",
            "StatusBox", "TxtStatus", "BtnPlay", "TxtPlay", "BtnReset", "BtnFlag",
            "BtnStart", "Spd1", "Spd2", "Spd3", "Spd4", "ChkFollow", "ChkLeft",
            "SldSize", "TxtSize", "BtnReload", "TxtHint"))
        u = self.ui
        u["TxtView"].Text = u"%s  ·  %s" % (self.view.Name, self.doc.Title)
        u["TitleBar"].MouseLeftButtonDown += lambda s, e: self._drag()
        u["BtnClose"].Click += lambda s, e: self.request_close()
        u["BtnPlay"].Click += lambda s, e: self.toggle_play()
        u["BtnReset"].Click += lambda s, e: self.do_reset(not self._shift())
        u["BtnFlag"].Click += lambda s, e: self.do_flag(self._shift())
        u["BtnStart"].Click += lambda s, e: self.queue("pick_start")
        u["BtnReload"].Click += lambda s, e: self.request_reload()
        speeds = [("Spd1", 0.25), ("Spd2", 0.5), ("Spd3", 1.0), ("Spd4", 2.0)]
        for name, val in speeds:
            rb = u[name]
            rb.IsChecked = abs(self.speed - val) < 1e-6
            rb.Checked += self._speed_handler(val)
        if not any(abs(self.speed - v) < 1e-6 for _, v in speeds):
            u["Spd3"].IsChecked = True
            self.speed = 1.0
        u["ChkFollow"].IsChecked = self.follow
        u["ChkFollow"].Click += lambda s, e: self._set_follow(bool(u["ChkFollow"].IsChecked))
        u["ChkLeft"].IsChecked = self.direction < 0
        u["ChkLeft"].Click += lambda s, e: self._set_left(bool(u["ChkLeft"].IsChecked))
        u["SldSize"].Value = round(math.log(self.size, 2) * 2) / 2.0 if self.size > 0 else 0
        self._show_size()
        u["SldSize"].ValueChanged += lambda s, e: self._set_size(2 ** u["SldSize"].Value)
        w.PreviewKeyDown += self._on_key
        w.Closed += lambda s, e: self.request_close()
        try:
            WindowInteropHelper(w).Owner = self.uiapp.MainWindowHandle
        except Exception:
            pass
        pos = self.cfg.get("hud")
        w.WindowStartupLocation = WindowStartupLocation.Manual
        area = SystemParameters.WorkArea
        if pos and area.Left - 50 < pos[0] < area.Right - 100 and area.Top - 20 < pos[1] < area.Bottom - 100:
            w.Left, w.Top = pos[0], pos[1]
        else:
            w.Left, w.Top = area.Right - 304 - 40, area.Top + 160
        self.timer = DispatcherTimer(DispatcherPriority.Background)
        self.timer.Interval = TimeSpan.FromMilliseconds(12)
        self.timer.Tick += self._on_timer
        self.timer.Start()
        w.Show()
        self.update_hud()

    def _drag(self):
        try:
            self.hud.DragMove()
        except Exception:
            pass

    def _shift(self):
        return (Keyboard.Modifiers & ModifierKeys.Shift) == ModifierKeys.Shift

    def _speed_handler(self, val):
        def h(s, e):
            self.speed = val
            self.save_prefs()
        return h

    def _set_follow(self, on):
        self.follow = on
        self.save_prefs()

    def _set_left(self, on):
        self.direction = -1 if on else 1
        self.flag = None
        self.save_prefs()
        self.playing = False
        self.reset(use_flag=False)
        self.status = "READY"
        self.kick()

    def _set_size(self, size):
        self.size = size
        self._show_size()
        self.save_prefs()
        self.flag = None
        self.playing = False
        self.queue("reload")

    def _show_size(self):
        s = self.size
        self.ui["TxtSize"].Text = (u"×%g" % s) if s >= 1 else (u"×%.2g" % s)

    def save_prefs(self):
        cfg = settings.load()
        cfg["speed"] = self.speed
        cfg["follow"] = self.follow
        cfg["left"] = self.direction < 0
        cfg["size"] = self.size
        try:
            if self.hud is not None:
                cfg["hud"] = [self.hud.Left, self.hud.Top]
        except Exception:
            pass
        settings.save(cfg)

    def _on_key(self, sender, e):
        k = e.Key
        handled = True
        if k == Key.Space:
            self.toggle_play()
        elif k == Key.Escape:
            self.pause()
        elif k == Key.R or k == Key.Home:
            self.do_reset(not self._shift())
        elif k == Key.F:
            self.do_flag(self._shift())
        elif k == Key.S:
            self.queue("pick_start")
        elif k == Key.C:
            self.ui["ChkFollow"].IsChecked = not self.follow
            self._set_follow(not self.follow)
        elif k in (Key.D1, Key.NumPad1):
            self.ui["Spd1"].IsChecked = True
        elif k in (Key.D2, Key.NumPad2):
            self.ui["Spd2"].IsChecked = True
        elif k in (Key.D3, Key.NumPad3):
            self.ui["Spd3"].IsChecked = True
        elif k in (Key.D4, Key.NumPad4):
            self.ui["Spd4"].IsChecked = True
        elif k == Key.Right:
            self.pause()
            self.step_frames(4 if self._shift() else 1)
        elif k == Key.Left:
            self.pause()
            self.rewind(4 if self._shift() else 1)
        else:
            handled = False
        e.Handled = handled

    def _on_timer(self, sender, e):
        if self.closed:
            return
        if (self.playing or self.dirty or self.actions) and not self.pending:
            self.kick()

    def kick(self):
        if self.event is None or self.closed:
            return
        self.pending = True
        try:
            self.event.Raise()
        except Exception:
            self.pending = False

    # -------------------------------------------------------------- controls
    def queue(self, name):
        self.actions.append(name)
        self.kick()

    def toggle_play(self):
        if self.playing:
            self.pause()
        else:
            self.playing = True
            self.watch.Restart()
            self.acc = 0.0
            self.status = "RIDING"
            if self.follow:
                self.actions.append("frame")
            self.kick()
        self.update_hud()

    def pause(self):
        if self.playing:
            self.playing = False
            self.status = "PAUSED"
            self.dirty = True
        self.update_hud()

    def do_reset(self, use_flag=True):
        self.playing = False
        self.reset(use_flag)
        self.status = "READY" if not (use_flag and self.flag) else "AT FLAG"
        if self.follow:
            self.actions.append("frame")
        self.update_hud()
        self.kick()

    def do_flag(self, remove=False):
        if remove:
            self.flag = None
            self.status = "FLAG REMOVED"
        else:
            self.flag = self.rider.snapshot()
            self.status = "FLAG SET  (%s)" % _fmt_time(self.rider.frame)
        self.build_static()
        self.dirty = True
        self.update_hud()
        self.kick()

    def step_frames(self, n):
        for _ in range(n):
            self._step()
        self.dirty = True
        self.update_hud()
        self.kick()

    def rewind(self, n):
        target = max(0, self.rider.frame - n)
        keys = [k for k in self.history if k <= target]
        if not keys:
            return
        base = max(keys)
        self.rider.restore(self.history[base])
        while self.rider.frame < target:
            self.rider.step(self.track)
        self.dirty = True
        self.update_hud()
        self.kick()

    def request_reload(self):
        self.queue("reload")

    def request_close(self):
        if self.closing:
            return
        self.closing = True
        self.playing = False
        self.save_prefs()
        if self.timer is not None:
            self.timer.Stop()
        self.kick()

    def close_now(self):
        """Called from another command (API context): tear down immediately."""
        self.closing = True
        self.playing = False
        try:
            if self.timer is not None:
                self.timer.Stop()
        except Exception:
            pass
        self._teardown(self.uiapp)

    def fail(self, text):
        self.playing = False
        self.status = "ERROR - see %APPDATA%\\RevitLineRider\\linerider.log"
        try:
            self.update_hud()
        except Exception:
            pass

    # ------------------------------------------------------------ simulation
    def _step(self):
        self.rider.step(self.track)
        f = self.rider.frame
        if f % HISTORY_EVERY == 0:
            self.history[f] = self.rider.snapshot()
        if self.rider.crashed and self.status == "RIDING":
            self.status = "CRASHED!"
            x, y = self.rider.center()
            settings.log("crash at frame %d (%s), rider at (%.0f, %.0f) units"
                         % (self.rider.crash_frame or 0, self.rider.crash_reason, x, y))

    def tick(self, uiapp):
        if self.closed:
            return
        if self.closing:
            self._teardown(uiapp)
            return
        uidoc = uiapp.ActiveUIDocument
        if not self.doc.IsValidObject or not self.view.IsValidObject:
            self.closing = True
            self._teardown(uiapp)
            return
        same_view = (uidoc is not None and uidoc.Document.Equals(self.doc)
                     and revitio.eid_int(uidoc.ActiveView.Id) == self.view_id)
        # queued actions that need the Revit API
        while self.actions:
            a = self.actions.pop(0)
            if a == "frame":
                if same_view:
                    self.zoom_to_rider(uidoc, force=False)
            elif a == "reload":
                self.playing = False
                rec = self.view_record()
                if rec.get("start"):
                    self.override_start = None      # e.g. Set Start was used
                if rec.get("unit"):
                    self.override_unit = None
                self.load_track()
                self.flag = None
                self.reset(use_flag=False)
                self.status = "TRACK RELOADED  (%d lines)" % len(self.polys)
            elif a == "pick_start":
                if same_view:
                    self.playing = False
                    self.status = "CLICK THE START POINT IN THE VIEW"
                    self.update_hud()
                    p = revitio.pick_point(uidoc, self.view, "Line Rider: click where the sled should start")
                    if p is not None:
                        u, v = self.frame_.uv(p)
                        settings.set_view(self.doc, self.view, start=[u, v])
                        self.override_start = [u, v]
                        self.load_track()
                        self.flag = None
                        self.reset(use_flag=False)
                        self.status = "NEW START SET"
                    else:
                        self.status = "READY"
                else:
                    self.status = "SWITCH BACK TO VIEW '%s'" % self.view.Name
            self.dirty = True
        if self.playing and not same_view:
            self.playing = False
            self.status = "PAUSED - switch back to '%s'" % self.view.Name
        if self.playing:
            dt = self.watch.Elapsed.TotalSeconds
            self.watch.Restart()
            self.acc += min(dt, 0.25) * self.speed * physics.FPS
            n = 0
            while self.acc >= 1.0 and n < MAX_STEPS_PER_TICK:
                self._step()
                self.acc -= 1.0
                n += 1
            if n == MAX_STEPS_PER_TICK:
                self.acc = 0.0
            self.dirty = True
        if self.dirty:
            self.update_geometry()
            if same_view:
                if self.playing and self.follow:
                    self.follow_camera(uidoc)
                uidoc.RefreshActiveView()
            self.dirty = False
            self.update_hud()

    # ------------------------------------------------------------- geometry
    def to_uv(self, x, y):
        return self.u0 + x * self.unit, self.v0 - y * self.unit

    def to_xyz(self, pt, layer=0):
        u, v = self.to_uv(pt[0], pt[1])
        return self.frame_.xyz(u, v, layer * LAYER_LIFT)

    def build_static(self):
        """Markers that only change on reload: accel chevrons, one-way ticks,
        start and flag markers."""
        tris, lines = [], []
        red = (215, 35, 35)
        purple = (125, 55, 190)
        for s in self.track.segments:
            if s.kind == physics.ACCEL_LINE:
                n = int(s.length // 12)
                for k in range(n):
                    c = 6 + 12 * k
                    px, py = s.ax + s.tx * c, s.ay + s.ty * c
                    # chevron pointing along the boost direction, on the riding side(s)
                    for side in (-1, 1):
                        ox, oy = s.nx * side * 1.6, s.ny * side * 1.6
                        a = (px - s.tx * 2.0 + ox * 2, py - s.ty * 2.0 + oy * 2)
                        b = (px + s.tx * 1.5 + ox, py + s.ty * 1.5 + oy)
                        c2 = (px - s.tx * 2.0 + ox * 0.6, py - s.ty * 2.0 + oy * 0.6)
                        tris.append((0, red, (a, b, c2)))
            elif s.kind == physics.ONEWAY:
                n = int(s.length // 6)
                for k in range(n):
                    c = 3 + 6 * k
                    px, py = s.ax + s.tx * c, s.ay + s.ty * c
                    # small ticks on the riding side
                    lines.append((0, purple, (px, py), (px - s.nx * 2.2 - s.tx * 1.2, py - s.ny * 2.2 - s.ty * 1.2)))
        # start marker: little green flag
        self._flag_shape(tris, lines, (-2.0, 5.5), (40, 170, 70))
        if self.flag is not None:
            fx, fy = self.flag["pos"][physics.PEG]
            self._flag_shape(tris, lines, (fx - 2.0, fy + 5.5), (31, 111, 235))
        self.static_tris = [(self.to_xyz(t[0], 0), self.to_xyz(t[1], 0), self.to_xyz(t[2], 0), render.color(col))
                            for (_, col, t) in tris]
        self.static_lines = [(self.to_xyz(a, 0), self.to_xyz(b, 0), render.color(col))
                             for (_, col, a, b) in lines]
        bb = self.track.bbox or [0, 0, 1, 1]
        pad = 400.0
        self._track_box = [bb[0] - pad, bb[1] - pad, bb[2] + pad, bb[3] + pad]

    def _flag_shape(self, tris, lines, base, rgb):
        bx, by = base
        lines.append((0, (30, 30, 30), (bx, by), (bx, by - 16)))
        tris.append((0, rgb, ((bx, by - 16), (bx + 8, by - 13), (bx, by - 10))))

    def update_geometry(self):
        if self.server is None:
            return
        tris, lines = physics.rider_shapes(self.rider)
        xt = list(self.static_tris)
        for (layer, col, t) in tris:
            xt.append((self.to_xyz(t[0], layer + 1), self.to_xyz(t[1], layer + 1),
                       self.to_xyz(t[2], layer + 1), render.color(col)))
        xl = list(self.static_lines)
        for (layer, col, a, b) in lines:
            xl.append((self.to_xyz(a, layer + 2), self.to_xyz(b, layer + 2), render.color(col)))
        self.server.tris = xt
        self.server.lines = xl
        # bounding box: track + rider
        bx = self._track_box
        xs = [p[0] for p in self.rider.pos]
        ys = [p[1] for p in self.rider.pos]
        x0, y0 = min(bx[0], min(xs) - 60), min(bx[1], min(ys) - 60)
        x1, y1 = max(bx[2], max(xs) + 60), max(bx[3], max(ys) + 60)
        corners = [self.to_xyz(p, 0) for p in ((x0, y0), (x1, y0), (x0, y1), (x1, y1))]
        d = self.frame_.D
        corners += [c + d * 2.0 for c in corners] + [c - d * 2.0 for c in corners]
        mn = XYZ(min(c.X for c in corners), min(c.Y for c in corners), min(c.Z for c in corners))
        mx = XYZ(max(c.X for c in corners), max(c.Y for c in corners), max(c.Z for c in corners))
        self.server.bbox = (mn, mx)

    def zoom_to_rider(self, uidoc, force=False):
        """Frame the rider so it is clearly visible (view ~VIEW_UNITS rider units
        tall). Without force it only zooms when the rider is off screen or tiny."""
        uiv = revitio.ui_view(uidoc, self.view)
        if uiv is None:
            return
        c = uiv.GetZoomCorners()
        au, av = self.frame_.uv(c[0])
        bu, bv = self.frame_.uv(c[1])
        w, h = abs(bu - au), abs(bv - av)
        x, y = self.rider.center()
        ru, rv = self.to_uv(x, y)
        inside = min(au, bu) < ru < max(au, bu) and min(av, bv) < rv < max(av, bv)
        units_tall = h / self.unit if self.unit else 0
        if not force and inside and 120 < units_tall < 1200:
            return
        aspect = (w / h) if h > 1e-9 else 1.6
        hh = VIEW_UNITS * self.unit * 0.5
        ww = hh * max(0.5, min(3.0, aspect))
        uiv.ZoomAndCenterRectangle(self.frame_.xyz(ru - ww, rv - hh), self.frame_.xyz(ru + ww, rv + hh))

    def follow_camera(self, uidoc):
        uiv = revitio.ui_view(uidoc, self.view)
        if uiv is None:
            return
        c = uiv.GetZoomCorners()
        a, b = c[0], c[1]
        au, av = self.frame_.uv(a)
        bu, bv = self.frame_.uv(b)
        cu, cv = (au + bu) * 0.5, (av + bv) * 0.5
        w, h = abs(bu - au), abs(bv - av)
        x, y = self.rider.center()
        ru, rv = self.to_uv(x, y)
        du, dv = ru - cu, rv - cv
        zu, zv = w * 0.12, h * 0.12          # dead zone around the centre
        su = du - max(-zu, min(zu, du))
        sv = dv - max(-zv, min(zv, dv))
        if abs(su) < w * 0.004 and abs(sv) < h * 0.004:
            return
        shift = self.frame_.R * su + self.frame_.U * sv
        uiv.ZoomAndCenterRectangle(a + shift, b + shift)

    # ---------------------------------------------------------------- HUD
    def update_hud(self):
        if self.hud is None or self.closed:
            return
        u = self.ui
        r = self.rider
        u["TxtTime"].Text = _fmt_time(r.frame)
        kmh = r.speed() * physics.FPS * self.unit * 0.3048 * 3.6
        u["TxtSpeed"].Text = "%d km/h" % int(round(kmh))
        u["TxtFrame"].Text = "frame %d" % r.frame
        st = self.status
        if r.crashed and st in ("RIDING", "PAUSED"):
            st = "CRASHED!"
        if st == "READY" and self.start_is_default:
            st = u"READY – press ⌖ to choose a start point"
        u["TxtStatus"].Text = st
        col = (0x25, 0x30, 0x40)
        if st.startswith("CRASHED"):
            col = (0x8B, 0x1E, 0x1E)
        elif st == "RIDING":
            col = (0x1A, 0x5C, 0x2E)
        elif st.startswith("ERROR"):
            col = (0x8B, 0x1E, 0x1E)
        u["StatusBox"].Background = SolidColorBrush(Color.FromRgb(col[0], col[1], col[2]))
        u["TxtPlay"].Text = u"❚❚" if self.playing else u"▶"

    # ------------------------------------------------------------- teardown
    def _teardown(self, uiapp):
        if self.closed:
            return
        self.closed = True
        try:
            if self.server is not None:
                render.unregister(self.server)
        except Exception:
            pass
        try:
            if self.hud is not None:
                self.hud.Close()
        except Exception:
            pass
        try:
            if self.event is not None:
                self.event.Dispose()
        except Exception:
            pass
        try:
            ad = AppDomain.CurrentDomain
            ad.SetData(KEY, None)
            ad.SetData("RevitLineRider.reload", None)
        except Exception:
            pass
        try:
            uidoc = uiapp.ActiveUIDocument
            if uidoc is not None:
                uidoc.RefreshActiveView()
        except Exception:
            pass
        try:
            settings.log("session closed: frame %d, RenderScene calls %d, render errors %d"
                         % (self.rider.frame, self.server.calls if self.server else -1,
                            self.server.errors if self.server else -1))
        except Exception:
            settings.log("session closed")


def close_existing():
    """Close a running session (call from a command = API context)."""
    act = AppDomain.CurrentDomain.GetData(KEY)
    if act is not None:
        try:
            act.Invoke()
        except Exception:
            settings.log("close_existing: " + traceback.format_exc())
        AppDomain.CurrentDomain.SetData(KEY, None)
        return True
    return False


def notify_reload():
    act = AppDomain.CurrentDomain.GetData("RevitLineRider.reload")
    if act is not None:
        try:
            act.Invoke()
        except Exception:
            pass


def launch(uiapp, start=None, unit=None):
    close_existing()
    uidoc = uiapp.ActiveUIDocument
    if uidoc is None:
        TaskDialog.Show("Line Rider", "Open a project first.")
        return None
    msg = revitio.check_view(uidoc.ActiveView)
    if msg:
        TaskDialog.Show("Line Rider", msg)
        return None
    g = Game(uiapp, start=start, unit=unit)
    try:
        if not g.start():
            return None
    except Exception:
        settings.log("launch error:\n" + traceback.format_exc())
        try:
            g._teardown(uiapp)
        except Exception:
            pass
        raise
    return g
