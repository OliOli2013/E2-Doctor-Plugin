import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
from e2_stubs import install,Session
install()
BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'src/usr/lib/enigma2/python/Plugins/Extensions'))
p=importlib.import_module('E2Doctor.plugin')
r=importlib.import_module('E2Doctor.runtime')
d=importlib.import_module('E2Doctor.dashboard')

class CoreTests(unittest.TestCase):
    def test_package_states(self):
        for state in ('install ok installed','hold ok installed','deinstall ok config-files','purge ok not-installed'):
            self.assertFalse(r.broken_package_status(state),state)
        for state in ('install ok unpacked','install reinstreq installed','install ok half-configured',''):
            self.assertTrue(r.broken_package_status(state),state)
    def test_dependency_providers(self):
        self.assertEqual(r.installed_names([{'package':'a','status':'hold ok installed','provides':'b (= 1), c'}, {'package':'removed','status':'deinstall ok config-files'}]),{'a','b','c'})
    def test_atomic_permissions_and_utf8_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'a'
            r.atomic_write(str(path),'ąęłó')
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            self.assertIn('ó',p.read_text(str(path),3))
            os.chmod(str(path),0o640)
            r.atomic_write(str(path),'replacement')
            self.assertEqual(path.stat().st_mode&0o777,0o640)
            self.assertEqual(path.read_text(),'replacement')
            self.assertEqual(len(list(Path(tmp).iterdir())),1)
    def test_process_timeout(self):
        start=time.monotonic()
        rc,_,_=r.run_command([sys.executable,'-c','import time; time.sleep(30)'],0.1)
        self.assertEqual(rc,124)
        self.assertLess(time.monotonic()-start,2)
    def test_urls_and_versions(self):
        self.assertTrue(r.valid_url('https://raw.githubusercontent.com/a/b'))
        for url in ('http://github.com/x','https://github.com.evil.test/x','https://user@github.com/x','https://github.com:444/x','file:///etc/passwd'):
            self.assertFalse(r.valid_url(url))
        with patch.object(p,'PLUGIN_VERSION','2.4'),patch.object(p,'PLUGIN_BUILD','20260910-1'):
            self.assertFalse(p._remote_is_newer('2.4.0','20260910-1'))
            self.assertTrue(p._remote_is_newer('2.4.0','20260910-2'))
            self.assertFalse(p._remote_is_newer('2.3','99999999-1'))
    def test_redaction(self):
        text=r.redact('https://alice:pass@example.test password=secret&x=1 token=abcdef https://host/live/bob/pwd/1.ts')
        for secret in ('alice','pass@','secret&','abcdef','bob','pwd'):
            self.assertNotIn(secret,text)
    def test_last_traceback_context(self):
        content='Traceback (most recent call last):\n  File "/usr/lib/enigma2/python/Plugins/Extensions/Old/plugin.py", line 2, in main\nImportError: old\nTraceback (most recent call last):\n  File "/usr/lib/enigma2/python/Plugins/Extensions/New/plugin.py", line 3, in main\nValueError: new\n'
        found=p.analyze_crashlog(content)
        self.assertEqual(found[0]['context']['plugin'],'New')
        self.assertNotIn('old',found[0]['message'])
    def test_ar_rejects_truncated_negative_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'bad.ipk'
            for blob in (b'!<arch>\nshort',b'!<arch>\n'+b'x'.ljust(48)+b'-1'.ljust(10)+b'`\n'):
                path.write_bytes(blob)
                with self.assertRaises(ValueError):r.read_ar_members(str(path))
    def test_archive_traversal_rejected(self):
        for name in ('../etc/passwd','/etc/passwd'):
            data=io.BytesIO()
            with tarfile.open(fileobj=data,mode='w') as archive:
                entry=tarfile.TarInfo(name);archive.addfile(entry)
            data.seek(0)
            with tarfile.open(fileobj=data) as archive:
                with self.assertRaises(ValueError):r.tar_members(archive)
    def test_cleanup_changed_file_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'crash.log';path.write_text('a')
            item={'path':str(path),'identity':[1,2,3,4],'size':1}
            with patch.object(p,'safe_flash_cleanup_candidates',return_value=[dict(item,identity=[1,2,3,5])]),patch.object(p,'record_operation'):
                self.assertEqual(p.perform_safe_flash_cleanup([item]),([],[],0))
                self.assertTrue(path.exists())
    def test_skin_bounds_and_names(self):
        for fhd,w,h,m in ((False,1180,680,34),(True,1580,900,48)):
            with patch.multiple(p,E2D_FHD=fhd,E2D_UI_W=w,E2D_UI_H=h,E2D_MARGIN=m):
                root=ET.fromstring(p.dashboard_skin_22())
                for widget in root:
                    x,y=map(int,widget.attrib['position'].split(','));ww,hh=map(int,widget.attrib['size'].split(','))
                    self.assertLessEqual(x+ww,w);self.assertLessEqual(y+hh,h)
        screen=p.E2DoctorDashboard(Session())
        self.assertIn('dashboard',screen)
        self.assertNotIn('categories',screen)
        for widget in ET.fromstring(screen.skin).findall('widget'):
            self.assertIn(widget.attrib.get('name') or widget.attrib.get('source'),screen)
        screen.close()
    def test_worker_ui_only_main_thread_and_close(self):
        from e2_stubs import Screen
        screen=Screen(Session());worker=d.Worker(screen);done=[]
        worker.start(lambda:42,lambda v,e:done.append((v,e)))
        time.sleep(.02)
        self.assertEqual(done,[])
        worker.poll();self.assertEqual(done,[(42,None)])
        worker.start(lambda:43,lambda v,e:done.append((v,e)))
        worker.close();time.sleep(.02);worker.poll()
        self.assertEqual(len(done),1)
    def test_all_checks_isolate_errors_and_cancel(self):
        with patch.object(p,'check_system',side_effect=RuntimeError('fixture'), __name__='check_system'),patch.object(p,'check_network'),patch.object(p,'check_storage_health'),patch.object(p,'check_opkg'),patch.object(p,'check_oscam'),patch.object(p,'check_live_tuner') as live:
            result=p.run_all_checks()
            self.assertTrue(any(x.get('solution_id')=='diagnostic_error' for x in result))
            live.assert_not_called()
        import threading
        cancel=threading.Event();cancel.set()
        self.assertEqual(p.run_all_checks(cancel=cancel),[])
    def test_updater_initializes_and_cleans_temp(self):
        screen=p.E2DoctorUpdateScreen(Session())
        directory=screen.temp_dir
        self.assertTrue(os.path.isdir(directory))
        screen.close()
        self.assertFalse(os.path.exists(directory))

class ReleaseTests(unittest.TestCase):
    def test_release_checksum_control_and_files(self):
        manifest=json.loads((BASE/'update.json').read_text())
        ipk=BASE/'releases'/manifest['download_url'].rsplit('/',1)[1]
        self.assertTrue(r.verify_ipk(str(ipk),manifest))
        members=r.read_ar_members(str(ipk))
        with tarfile.open(fileobj=io.BytesIO(members['control.tar.gz'])) as archive:
            control=archive.extractfile('./control').read().decode()
            self.assertIn('Version: '+p.PLUGIN_VERSION,control)
            checks=archive.extractfile('./md5sums').read().decode().splitlines()
        with tarfile.open(fileobj=io.BytesIO(members['data.tar.gz'])) as archive:
            for line in checks:
                checksum,name=line.split('  ',1)
                self.assertEqual(hashlib.md5(archive.extractfile('./'+name).read()).hexdigest(),checksum)
            for item in archive:
                self.assertNotIn('__pycache__',item.name)
                self.assertEqual(item.uid,0)
            self.assertEqual(archive.getmember('./usr/bin/e2doctor-report').mode,0o755)
        for changes in ({'sha256':'0'*64},{'version':'99.0'}):
            with self.assertRaises(ValueError):r.verify_ipk(str(ipk),dict(manifest,**changes))
    def test_update_does_not_claim_old_files_installed(self):
        screen=p.E2DoctorUpdateScreen(Session())
        screen.install_manifest={'version':'99.0','build':'future'}
        screen.console_output=['opkg returned zero but did nothing']
        screen._install_finished(0)
        self.assertIn('BŁĄD',screen['status'].getText())
        screen.close()
    def test_manifest_arrives_after_paint(self):
        screen=p.E2DoctorUpdateScreen(Session())
        with patch.object(p,'fetch_update_manifest',return_value={'version':'99.0','build':'1','notes':['fixture']}):
            screen.check_update()
            self.assertTrue(screen.busy)
            self.assertIsNone(screen.manifest)
            time.sleep(.03)
            screen.update_worker.poll()
            self.assertTrue(screen.update_available)
            self.assertFalse(screen.busy)
        screen.close()
    def test_all_secondary_screens_construct(self):
        classes=[(p.E2DoctorTextScreen,('Test','Body')),(p.E2DoctorSolutionScreen,({'title':'Test','summary':'Test','status':'WARN'},)),(p.E2DoctorResultsScreen,('Test',[])),(p.E2DoctorQuickRepairScreen,([],)),(p.E2DoctorSettingsScreen,()),(p.E2DoctorHistoryScreen,()),(p.E2DoctorIPKBrowser,()),(p.E2DoctorTools,())]
        with patch.object(p,'load_history',return_value=[]):
            for cls,args in classes:
                screen=cls(Session(),*args)
                for widget in ET.fromstring(screen.skin).findall('widget'):
                    name=widget.attrib.get('name') or widget.attrib.get('source')
                    self.assertIn(name,screen,cls.__name__+': '+name)
                screen.close()
    def test_update_skin_inside_bounds(self):
        root=ET.fromstring(p.E2DoctorUpdateScreen.skin)
        sw,sh=map(int,root.attrib['size'].split(','))
        for node in root:
            x,y=map(int,node.attrib['position'].split(','));w,h=map(int,node.attrib['size'].split(','))
            self.assertLessEqual(x+w,sw);self.assertLessEqual(y+h,sh)
    def test_lamedb5_recognized(self):
        def exists(path):return path in ('/etc/enigma2/bouquets.tv','/etc/enigma2/lamedb5')
        with patch.object(p.os.path,'isfile',side_effect=exists),patch.object(p.os.path,'exists',side_effect=exists),patch.object(p.os.path,'getsize',return_value=1024),patch.object(p,'find_missing_bouquet_refs',return_value=[]),patch.object(p,'parse_bouquet_references',return_value=[]):
            results=[];p.check_bouquets(results)
            self.assertEqual(results[0]['status'],'OK')

class ClassicTests(unittest.TestCase):
    def test_scan_runs_in_background_and_retains_selection(self):
        screen=p.E2DoctorDashboard(Session())
        screen['dashboard'].moveToIndex(3)
        sample=[{'title':'Pamięć flash','status':'OK','summary':'fixture','module':'system'}]
        with patch.object(p,'run_all_checks',return_value=sample),patch.object(p,'check_live_tuner') as live,patch.object(p,'save_history_snapshot'),patch.object(p,'load_history',return_value=[]):
            screen.scan()
            self.assertTrue(screen.worker.busy)
            self.assertEqual(screen.results,[])
            time.sleep(.03);screen.worker.poll()
            live.assert_called_once()
            self.assertEqual(screen.results,sample)
            self.assertEqual(screen['dashboard'].getSelectedIndex(),3)
        screen.close()
    def test_report_requested_before_scan_waits_for_results(self):
        screen=p.E2DoctorDashboard(Session())
        with patch.object(screen,'scan') as scan:
            screen.save_report()
            scan.assert_called_once()
            self.assertIsNotNone(screen.pending)
            self.assertEqual(screen.session.opened,[])
        screen.close()

if __name__=='__main__':unittest.main()
