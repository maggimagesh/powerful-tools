import ctypes
import datetime
import shutil
import signal
import subprocess
import time

from gi.repository import GLib, Gtk

from . import core

REASON = 'Powerful Tools Awake is keeping the computer awake'


def _die_with_parent():
    try:
        ctypes.CDLL('libc.so.6').prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG
    except OSError:
        pass


class AwakeController(object):
    def __init__(self, app):
        self.app = app
        self.cookie = 0
        self.proc = None
        self.end = None
        self.timer = 0
        self.listeners = []
        self.held = False

    @property
    def active(self):
        return bool(self.cookie or self.proc)

    def start(self, seconds=None, screen_on=True):
        self.stop(notify=False)
        flags = Gtk.ApplicationInhibitFlags.SUSPEND
        if screen_on:
            flags |= Gtk.ApplicationInhibitFlags.IDLE
        self.cookie = self.app.inhibit(self.app.get_active_window(), flags, REASON)
        if not self.cookie and shutil.which('systemd-inhibit'):
            what = 'sleep:idle' if screen_on else 'sleep'
            try:
                self.proc = subprocess.Popen(
                    ['systemd-inhibit', '--what=' + what, '--who=' + core.APP_NAME, '--why=' + REASON,
                     '--mode=block', 'sleep', 'infinity'],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=_die_with_parent)
                time.sleep(0.2)
                if self.proc.poll() is not None:
                    self.proc = None
            except OSError:
                self.proc = None
        if not self.active:
            self._changed()
            return False
        if seconds:
            self.end = time.monotonic() + seconds
            self.timer = GLib.timeout_add_seconds(1, self._tick)
        self._changed()
        return True

    def stop(self, notify=True):
        if self.cookie:
            self.app.uninhibit(self.cookie)
            self.cookie = 0
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0
        self.end = None
        if notify:
            self._changed()

    def remaining(self):
        return None if self.end is None else max(0, int(self.end - time.monotonic()))

    def _tick(self):
        if self.remaining() == 0:
            self.timer = 0
            self.stop()
            return False
        self._changed()
        return True

    def toggle(self):
        """Keyboard shortcut: keep awake indefinitely, or turn it off. Returns the new state."""
        if self.active:
            self.stop()
        else:
            self.start(None, self.app.settings.get('awake_screen_on', True))
        return self.active

    def _changed(self):
        # keep running in the background while awake, even with no window open
        if self.active and not self.held:
            self.app.hold()
            self.held = True
        elif not self.active and self.held:
            self.app.release()
            self.held = False
        for cb in self.listeners:
            cb()


def fmt_secs(s):
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return '%d:%02d:%02d' % (h, m, sec)


class AwakePage(core.Page):
    ID = 'awake'
    TITLE = 'Awake'
    ICON = 'weather-clear-night-symbolic'
    DESC = 'Keep your computer awake without changing its power settings.'

    def __init__(self, app):
        core.Page.__init__(self, app)
        self.ctl = app.awake
        s = app.settings
        self._busy = False
        self.status = core.label('', 'pt-heading')
        self.add_widget(core.card(self.status))

        self.r_off = Gtk.RadioButton.new_with_label(None, 'Off (use system power plan)')
        self.r_inf = Gtk.RadioButton.new_with_label_from_widget(self.r_off, 'Keep awake indefinitely')
        self.r_for = Gtk.RadioButton.new_with_label_from_widget(self.r_off, 'Keep awake for a time interval')
        self.r_until = Gtk.RadioButton.new_with_label_from_widget(self.r_off, 'Keep awake until a time today/tomorrow')
        self.hours = core.spin(0, 99, s.get('awake_hours', 1))
        self.mins = core.spin(0, 59, s.get('awake_minutes', 0))
        now = datetime.datetime.now()
        self.u_h = core.spin(0, 23, s.get('awake_until_h', (now.hour + 1) % 24))
        self.u_m = core.spin(0, 59, s.get('awake_until_m', 0))
        interval = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=4)
        for w in (core.label('Hours', xalign=1), self.hours, core.label('Minutes', xalign=1), self.mins):
            interval.add(w)
        until = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=4)
        for w in (core.label('Hour', xalign=1), self.u_h, core.label('Minute', xalign=1), self.u_m):
            until.add(w)
        self.screen = Gtk.Switch(active=s.get('awake_screen_on', True))
        for w in (interval, until):
            w.set_margin_start(28)
        self.add_widget(core.card(self.r_off, self.r_inf, self.r_for, interval, self.r_until, until,
                                  title='Mode'))
        self.add_widget(core.card(core.row('Keep screen on', 'Also stop the screen from dimming and locking.',
                                           self.screen)))
        for r in (self.r_off, self.r_inf, self.r_for, self.r_until):
            r.connect('toggled', self._on_mode)
        for w in (self.hours, self.mins, self.u_h, self.u_m):
            w.connect('value-changed', self._on_values)
        self.screen.connect('notify::active', self._on_values)
        self.ctl.listeners.append(self._refresh)
        self.connect('destroy', lambda *_: self.ctl.listeners.remove(self._refresh))
        self._refresh()

    def _save(self):
        s = self.app.settings
        s.data.update(awake_hours=int(self.hours.get_value()), awake_minutes=int(self.mins.get_value()),
                      awake_until_h=int(self.u_h.get_value()), awake_until_m=int(self.u_m.get_value()),
                      awake_screen_on=self.screen.get_active())
        s.save()

    def _on_values(self, *_):
        self._save()
        if not self.r_off.get_active():
            self._apply()

    def _on_mode(self, btn):
        if btn.get_active():
            self._apply()

    def _apply(self):
        if self._busy:
            return
        screen_on = self.screen.get_active()
        if self.r_off.get_active():
            self.ctl.stop()
            return
        secs = None
        if self.r_for.get_active():
            secs = int(self.hours.get_value()) * 3600 + int(self.mins.get_value()) * 60
            if secs <= 0:
                self.ctl.stop()
                self.toast('Choose a duration longer than zero.', error=True)
                return
        elif self.r_until.get_active():
            now = datetime.datetime.now()
            t = now.replace(hour=int(self.u_h.get_value()), minute=int(self.u_m.get_value()),
                            second=0, microsecond=0)
            if t <= now:
                t += datetime.timedelta(days=1)
            secs = int((t - now).total_seconds())
        if not self.ctl.start(secs, screen_on):
            self.toast('Your desktop does not allow keeping the system awake (no session manager or logind).',
                       error=True)

    def _refresh(self):
        c = self.ctl
        if not c.active:
            self.status.set_text('Status: off. The computer follows its normal power settings.')
            if not self.r_off.get_active():
                self._busy = True
                self.r_off.set_active(True)
                self._busy = False
        else:
            rem = c.remaining()
            if self.r_off.get_active():  # turned on by the keyboard shortcut
                self._busy = True
                self.r_inf.set_active(True)
                self._busy = False
            self.status.set_text('Status: keeping awake' + (' indefinitely' if rem is None
                                                            else ' for %s more' % fmt_secs(rem)))
