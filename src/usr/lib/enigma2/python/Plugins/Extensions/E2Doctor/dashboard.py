# -*- coding: utf-8 -*-
"""Background worker shared by the classic UI and tools."""
import datetime
import queue
import threading
from . import plugin as p
from Components.Pixmap import Pixmap
from enigma import eTimer


class Worker:
    def __init__(self, owner):
        self.queue = queue.Queue()
        self.alive = True
        self.busy = False
        self.cancel = threading.Event()
        self.timer = eTimer()
        self.connection = None
        try:
            self.timer.callback.append(self.poll)
        except AttributeError:
            self.connection = self.timer.timeout.connect(self.poll)
        owner.onClose.append(self.close)

    def start(self, operation, finished, progress=None):
        if self.busy or not self.alive:
            return False
        self.busy = True
        self.cancel.clear()
        self.finished = finished
        self.progress = progress
        def run():
            try:
                value = operation()
                self.queue.put(('done', value, None))
            except Exception as error:
                self.queue.put(('done', None, str(error)))
        thread = threading.Thread(target=run, name='E2DoctorWorker')
        thread.daemon = True
        thread.start()
        self.timer.start(100, False)
        return True

    def notify(self, *args):
        self.queue.put(('progress', args, None))

    def poll(self):
        if not self.alive:
            return
        for _ in range(50):
            try:
                kind, value, error = self.queue.get_nowait()
            except queue.Empty:
                return
            if kind == 'progress':
                if self.progress:
                    self.progress(*value)
            else:
                self.busy = False
                self.timer.stop()
                self.finished(value, error)
                return

    def close(self):
        self.alive = False
        self.cancel.set()
        self.timer.stop()
        self.finished = None
        self.progress = None

