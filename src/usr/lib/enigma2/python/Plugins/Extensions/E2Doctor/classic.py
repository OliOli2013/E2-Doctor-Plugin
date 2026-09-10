# -*- coding: utf-8 -*-
"""Original 2.3 presentation with background scans and safe screen lifecycle."""
from . import plugin as p
from .dashboard import Worker

ClassicBase = p.E2DoctorDashboard


class E2DoctorDashboard(ClassicBase):
    skin = p.dashboard_skin_22()

    def __init__(self, session):
        self.pending = None
        ClassicBase.__init__(self, session)
        self.worker = Worker(self)
        self['title'].setText('E2 Doctor ' + p.PLUGIN_VERSION)
        self['brand_badge'].setText(p.L('DIAGNOSTYKA  •  NAPRAWA  •  MONITORING', 'DIAGNOSTICS  •  REPAIR  •  MONITORING'))

    def first_show(self):
        if self._scan_started:
            return
        self._scan_started = True
        if self.settings.get('auto_scan', True):
            self.scan()

    def refresh_dashboard(self):
        index = self['dashboard'].getSelectedIndex()
        p._dashboard_refresh_23(self)
        if index >= 0:
            self['dashboard'].moveToIndex(index)

    def scan(self):
        if self.worker.busy:
            return
        self['change'].setText(p.L('Trwa diagnostyka…', 'Scanning…'))
        self['key_red'].setText(p.L('Skanowanie…', 'Scanning…'))
        self['recommendation'].setText(p.L('Możesz zamknąć panel przyciskiem EXIT.', 'You can close the panel with EXIT.'))
        self.previous_history = p.load_history()
        self.worker.start(lambda: p.run_all_checks(progress=self.worker.notify, cancel=self.worker.cancel), self.scan_done, self.scan_progress)

    def scan_progress(self, index, total, name):
        self['change'].setText(p.L('Etap %d / %d', 'Step %d / %d') % (index + 1, total))
        self['recommendation'].setText(p.L('Trwa diagnostyka: ', 'Scanning: ') + name.replace('check_', '').replace('_', ' '))

    def scan_done(self, results, error):
        self['key_red'].setText(p.L('Skanuj', 'Scan'))
        if error:
            self.pending = None
            self['change'].setText(p.L('Błąd diagnostyki: ', 'Diagnostic error: ') + error)
            return
        self.results = results
        try:
            p.check_live_tuner(self.results, self.session)
        except Exception as error:
            p.add_result(self.results, p.STATUS_INFO, 'Aktywna głowica i sygnał', str(error))
        p.assign_modules(self.results)
        previous = self.previous_history[0] if self.previous_history else None
        change = p.compare_snapshots(p.compact_snapshot(self.results), previous)
        try:
            p.save_history_snapshot(self.results)
        except Exception as error:
            change = p.L('Skan gotowy; nie zapisano historii: ', 'Scan complete; history not saved: ') + str(error)
        self.update_summary(change)
        self.refresh_dashboard()
        callback, self.pending = self.pending, None
        if callback:
            callback()

    def open_selected(self):
        if self.worker.busy:
            return
        key = self.selected_key()
        if key == 'py3':
            self['change'].setText(p.L('Trwa analiza zgodności…', 'Checking compatibility…'))
            self.worker.start(p.python3_compatibility_report, self.compatibility_done)
            return
        if key not in ('update', 'history', 'ipk', 'tools') and not self.results:
            self.pending = self.open_selected
            self.scan()
            return
        ClassicBase.open_selected(self)

    def compatibility_done(self, text, error):
        self['change'].setText(p.L('Analiza zakończona', 'Analysis complete'))
        if error:
            self.session.open(p.MessageBox, error, p.MessageBox.TYPE_ERROR)
        else:
            self.session.open(p.E2DoctorTextScreen, p.L('Zgodność Python 3', 'Python 3 compatibility'), text)

    def save_report(self):
        if self.worker.busy:
            return
        if not self.results:
            self.pending = self.save_report
            self.scan()
            return
        self['change'].setText(p.L('Zapisywanie raportu…', 'Saving report…'))
        self.worker.start(lambda: p.make_report(self.results), self.report_done)

    def report_done(self, path, error):
        self['change'].setText(p.L('Zapis zakończony', 'Save complete'))
        self.session.open(p.MessageBox, error or p.L('Raport zapisano:\n', 'Report saved:\n') + path,
                          p.MessageBox.TYPE_ERROR if error else p.MessageBox.TYPE_INFO)

    def open_tools(self):
        if not self.worker.busy:
            ClassicBase.open_tools(self)

    def open_settings(self):
        if not self.worker.busy:
            ClassicBase.open_settings(self)

    def settings_closed(self, changed=False):
        ClassicBase.settings_closed(self, changed)
        self['brand_badge'].setText(p.L('DIAGNOSTYKA  •  NAPRAWA  •  MONITORING', 'DIAGNOSTICS  •  REPAIR  •  MONITORING'))

    def open_update(self):
        if not self.worker.busy:
            self.session.open(p.E2DoctorUpdateScreen)
