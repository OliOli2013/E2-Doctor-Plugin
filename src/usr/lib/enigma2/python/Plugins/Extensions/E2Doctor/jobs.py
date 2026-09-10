# -*- coding: utf-8 -*-
"""Progress screen for potentially slow tools; UI updates stay on the GUI thread."""
from . import plugin as p
from .dashboard import Worker


class JobScreen(p.Screen):
    skin = '''<screen name="E2DoctorJob" position="center,center" size="700,210" flags="wfNoBorder" backgroundColor="#06121E">
      <widget name="title" position="25,25" size="650,60" font="Regular;25" foregroundColor="#00BCE8" />
      <widget name="status" position="25,100" size="650,80" font="Regular;21" foregroundColor="#CBD7E2" />
    </screen>'''
    def __init__(self,session,title,operation):
        p.Screen.__init__(self,session)
        self['title']=p.Label(title)
        self['status']=p.Label(p.L('Trwa operacja. Poczekaj na jej zakończenie…','Operation in progress. Please wait…'))
        self.worker=Worker(self)
        self.operation=operation
        self.started=False
        self.onShown.append(self.start)
    def start(self):
        if not self.started:
            self.started=True
            self.worker.start(self.operation,lambda value,error:self.close(value,error))


def install():
    original=p.E2DoctorActionMixin._execute_pending_action
    def execute(self):
        action=getattr(self,'_e2d_pending_action','')
        tasks={
            'find_large_files':p.largest_files_text,
            'show_processes':p.top_memory_processes_text,
            'network_test':p.network_diagnostic_text,
            'storage_diagnostic':p.storage_diagnostic_text,
            'restart_oscam':p.restart_oscam_service,
            'sync_time':p.sync_system_time,
            'safe_ram_refresh':p.safe_ram_refresh,
            'emergency_report':p.emergency_report,
            'safe_flash_cleanup':lambda:p.perform_safe_flash_cleanup(getattr(self,'_e2d_flash_entries',None)),
            'cleanup_crashlogs':p.cleanup_old_crashlogs,
        }
        if action not in tasks:
            return original(self)
        def done(value,error):
            if error:
                return self._show_action_message(p.L('Operacja nie powiodła się:\n','Operation failed:\n')+error,False,True)
            if action in ('find_large_files','show_processes','network_test','storage_diagnostic'):
                return self._open_action_text(p.action_title(action),value,p.L('Analiza bez zmiany konfiguracji','Read-only analysis'))
            if action=='safe_flash_cleanup':
                removed,failed,recovered=value
                message=p.L('Usunięto: %d; odzyskano: %s','Removed: %d; recovered: %s')%(len(removed),p.format_bytes(recovered))
                if failed:
                    message+='\n'+'\n'.join(failed)
                return self._show_action_message(message,bool(removed),bool(failed))
            if action=='safe_ram_refresh':
                before,after=value
                message=p.L('Dostępny RAM przed: %s\nPo: %s','Available RAM before: %s\nAfter: %s')%(p.format_bytes(before),p.format_bytes(after))
            elif action=='emergency_report':
                message=p.L('Raport zapisano:\n','Report saved:\n')+value
            elif action=='cleanup_crashlogs':
                message=p.L('Usunięto crashlogów: %d','Crashlogs removed: %d')%len(value)
            else:
                message=p.L('Polecenie usługi zakończyło się poprawnie.\n','Service command completed successfully.\n')+str(value[0])
            self._show_action_message(message,action!='emergency_report')
        self.session.openWithCallback(done,JobScreen,p.action_title(action),tasks[action])
    p.E2DoctorActionMixin._execute_pending_action=execute

    original_tools_execute = p.E2DoctorTools.execute
    mapping = {'safe_flash':'safe_flash_cleanup','safe_ram':'safe_ram_refresh','storage_diag':'storage_diagnostic',
               'reload':'reload_bouquets','lock':'remove_opkg_lock','logs':'cleanup_crashlogs','oscam':'restart_oscam',
               'processes':'show_processes','files':'find_large_files','emergency':'emergency_report','gui':'restart_gui'}
    def tool_execute(self):
        index=self['list'].getSelectedIndex()
        if index<0 or index>=len(self.tool_entries):
            return
        action=self.tool_entries[index][1]
        if action in mapping:
            self.request_action(mapping[action],{},self._new_action_finished)
        else:
            original_tools_execute(self)
    p.E2DoctorTools.execute=tool_execute
    old_init=p.E2DoctorTools.__init__
    def tool_init(self,session):
        old_init(self,session)
        def describe():
            index=self['list'].getSelectedIndex()
            if 0<=index<len(self.tool_entries):
                title,action,subtitle=self.tool_entries[index]
                self.session.open(p.E2DoctorTextScreen,p.translate_text(title),p.translate_text(subtitle))
        self['help_actions']=p.ActionMap(['ColorActions'],{'yellow':describe},-2)
    p.E2DoctorTools.__init__=tool_init
