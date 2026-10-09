import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import sys, unittest, time, tempfile, json, subprocess, shutil
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QProcess
from main import MainWindow
from telemetry_factory import NullTelemetry
from preview_sync import PreviewSync

class FakeMedia:
    def __init__(self): self.rate=1.;self.pos=0;self.length=100000;self.seeks=[];self.plays=0;self.pauses=0
    def duration(self):return self.length
    def playbackRate(self):return self.rate
    def setPlaybackRate(self,r):self.rate=r
class FakePlayer:
    def __init__(self):self.player=FakeMedia()
    def position(self):return self.player.pos
    def set_position(self,p):self.player.pos=p;self.player.seeks.append(p)
    def play(self):self.player.plays+=1
    def pause(self):self.player.pauses+=1
class Clock:
    def __init__(self):self.t=0
    def start(self):self.t=0
    def elapsed(self):return self.t

class PreviewTests(unittest.TestCase):
    def test_4423_no_periodic_seek_60_seconds(self):
        p=[FakePlayer(),FakePlayer()];sync=PreviewSync(p);sync.clock=Clock();sync.offset=4423;sync.play()
        for t in range(0,65000,200):
            sync.clock.t=t
            for i,player in enumerate(p):player.player.pos=max(0,t-(4423 if i else 0))
            sync.tick()
            if t<4423:self.assertEqual(p[1].player.plays,0)
        self.assertEqual(p[1].player.plays,1);self.assertEqual(sync.hard_seek_count,0)
        self.assertEqual(p[1].player.seeks,[])
    def test_negative_global_and_single_shared_seek(self):
        p=[FakePlayer(),FakePlayer()];sync=PreviewSync(p);sync.offset=-4423
        self.assertEqual(sync.duration(),104423)
        sync.seek(5000)
        self.assertEqual(p[0].player.seeks,[577]);self.assertEqual(p[1].player.seeks,[5000])
    def test_soft_rate_and_sustained_emergency(self):
        p=[FakePlayer(),FakePlayer()];sync=PreviewSync(p);sync.clock=Clock();sync.play()
        sync.clock.t=200;p[0].player.pos=100;p[1].player.pos=200;sync.tick()
        self.assertEqual(p[0].player.rate,1.02)
        for t in range(5000,6800,200):sync.clock.t=t;sync.tick()
        self.assertEqual(sync.hard_seek_count,2)

class ExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        cls._media_dir = tempfile.TemporaryDirectory(prefix='sportcam-test-media-')
        cls._media_paths = None
        from video_encoder import resolve_legacy_ffmpeg
        ffmpeg = resolve_legacy_ffmpeg('CPU')
        if ffmpeg and (Path(ffmpeg).is_file() or shutil.which(ffmpeg)):
            paths = [Path(cls._media_dir.name) / 'tone440.mp4', Path(cls._media_dir.name) / 'tone880.mp4']
            for path, frequency in zip(paths, (440, 880)):
                command = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-y',
                           '-f', 'lavfi', '-i', 'color=c=black:s=64x36:r=5',
                           '-f', 'lavfi', '-i', f'sine=frequency={frequency}:sample_rate=48000',
                           '-t', '2', '-shortest', '-c:v', 'libx264', '-preset', 'ultrafast',
                           '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(path)]
                result = subprocess.run(command, capture_output=True, text=True, timeout=30)
                if result.returncode:
                    cls._media_paths = None
                    break
            else:
                cls._media_paths = paths

    @classmethod
    def tearDownClass(cls):
        cls._media_dir.cleanup()

    def setUp(self):
        self.w=MainWindow()
        paths = self._media_paths or [Path(self._media_dir.name) / 'tone440.mp4', Path(self._media_dir.name) / 'tone880.mp4']
        self.w.telemetry1=NullTelemetry(str(paths[0]))
        self.w.telemetry2=NullTelemetry(str(paths[1]))
    def tearDown(self):self.w.close();self.w.deleteLater();self.app.processEvents()
    def pump(self,condition,timeout=15):
        end=time.monotonic()+timeout
        while not condition() and time.monotonic()<end:self.app.processEvents();time.sleep(.01)
        self.assertTrue(condition())
    def test_mainwindow_export_starts_qprocess(self):
        import main
        if not getattr(main, '_HAS_AMF', False):
            self.skipTest("Requires AMD GPU for real D3D11 export")
        helper = Path(main.__file__).resolve().parent.parent / 'bin' / 'KomparatorGpuExporter.exe'
        if not helper.is_file():
            self.skipTest("Build the native GPU exporter to run the AMD integration test")
        if not self._media_paths:
            self.skipTest("Requires FFmpeg with lavfi and libx264 to create temporary test clips")
        with tempfile.TemporaryDirectory() as d:
            output=str(Path(d)/'out.mp4')
            self.w.encoder_combo.setCurrentText('AMD AMF')
            self.w.backend_combo.setCurrentIndex(1)
            self.w.scale_combo.setCurrentText('x0.25')
            self.w.chk_overlay.setChecked(False)
            with patch('main.QFileDialog.getSaveFileName',return_value=(output,'')),patch.object(QMessageBox,'critical') as error,patch.object(QMessageBox,'information'):
                self.w.export_video()
                self.pump(lambda:self.w._export_started_at is not None or not self.w._is_exporting)
                self.assertIsNotNone(self.w._export_started_at,error.call_args)
                self.pump(lambda:not self.w._is_exporting,40)
                self.assertFalse(error.called,error.call_args)
                self.assertTrue(Path(output).exists())
    def test_legacy_mainwindow_export_starts(self):
        if not self._media_paths:
            self.skipTest("Requires FFmpeg with lavfi and libx264 to create temporary test clips")
        with tempfile.TemporaryDirectory() as d:
            output=str(Path(d)/'legacy.mp4')
            self.w.backend_combo.setCurrentIndex(2)
            self.w.encoder_combo.setCurrentText('CPU')
            self.w.scale_combo.setCurrentText('x0.25')
            self.w.chk_overlay.setChecked(False)
            with patch('main.QFileDialog.getSaveFileName',return_value=(output,'')),patch.object(QMessageBox,'critical') as error,patch.object(QMessageBox,'information'):
                self.w.export_video()
                self.pump(lambda:not self.w._is_exporting,40)
                self.assertFalse(error.called,error.call_args)
                self.assertIsNotNone(self.w._export_started_at)
                self.assertTrue(Path(output).exists())

    def test_missing_complete_is_not_success(self):
        self.w._export_clicked_at=time.perf_counter();self.w._active_backend='d3d11';self.w._is_exporting=True
        self.w._cancel_requested=False;self.w._last_gpu_error='';self.w._last_gpu_metrics=None
        with patch.object(QMessageBox,'critical') as error,patch.object(QMessageBox,'information') as success:
            self.w._start_export_process(sys.executable,['-c',"print('ordinary log without completion')"])
            self.pump(lambda:error.called)
            self.assertFalse(success.called)
            self.assertIn('no success completion',error.call_args.args[2])

    def test_crash_is_reported(self):
        self.w._export_clicked_at=time.perf_counter();self.w._active_backend='d3d11';self.w._is_exporting=True
        self.w._cancel_requested=False;self.w._last_gpu_error='';self.w._last_gpu_metrics=None
        with patch.object(QMessageBox,'critical') as error:
            self.w._start_export_process(sys.executable,['-c','import os;os.abort()'])
            self.pump(lambda:error.called)
            self.assertIn('Crashed',error.call_args.args[2])

    def test_probe_auto_fallback_and_forced_error(self):
        if not self._media_paths:
            self.skipTest("Requires FFmpeg with lavfi and libx264 to create temporary test clips")
        from export_prepare import prepare_export
        options=dict(output='out.mp4',scale=.25,hw='AMD AMF',codec='H.264',backend=0,bitrate=5,audio='mute',layout='left_right',offset=4423,overlay=False)
        with tempfile.TemporaryDirectory() as d,patch('export_prepare.resolve_export_helper',return_value=(Path(__file__).resolve(),None)),patch('export_prepare.probe_gpu_exporter',return_value=(False,'specific probe failure')),patch('export_prepare.probe_encoder_limit',return_value=(3840,2160)):
            result=prepare_export(options,(self.w.telemetry1,self.w.telemetry2),d)
            self.assertEqual(result[0],'legacy')
            options['backend']=1
            with self.assertRaisesRegex(RuntimeError,'specific probe failure'):
                prepare_export(options,(self.w.telemetry1,self.w.telemetry2),d)

    def test_failed_to_start_is_reported(self):
        self.w._export_clicked_at=time.perf_counter();self.w._active_backend='d3d11';self.w._is_exporting=True
        self.w._cancel_requested=False;self.w._last_gpu_error='';self.w._last_gpu_metrics=None
        with patch.object(QMessageBox,'critical') as error:
            self.w._start_export_process('missing-exporter-123.exe',[])
            self.pump(lambda:error.called)
            text=error.call_args.args[2]
            self.assertIn('FailedToStart',text);self.assertIn('backend=d3d11',text)
    def test_fragmented_output_error_and_no_complete_rejected(self):
        self.w._export_clicked_at=time.perf_counter();self.w._active_backend='d3d11';self.w._is_exporting=True
        self.w._cancel_requested=False;self.w._last_gpu_error='';self.w._last_gpu_metrics=None
        code="import sys,time;sys.stdout.write('{\"type\":\"error\",');sys.stdout.flush();time.sleep(.1);print('\"message\":\"intentional failure\"}')"
        with patch.object(QMessageBox,'critical') as error:
            self.w._start_export_process(sys.executable,['-c',code]);self.pump(lambda:error.called)
            self.assertIn('intentional failure',error.call_args.args[2]);self.assertIn('intentional failure',self.w._export_log)
    def test_overlay_does_not_relayout_on_time_change(self):
        p=self.w.player1;before=p.layout_update_count
        for i in range(100):p.set_overlay(f'TIME : {i/5:.3f}s')
        self.assertEqual(p.layout_update_count,before)

    def test_export_preview_option_is_available(self):
        """The performance-safe preview can be disabled from Options."""
        from options_dialog import OptionsDialog
        dialog = OptionsDialog(self.w)
        self.assertTrue(dialog.chk_export_preview.isChecked())
        # Toolbar layout verification: controls at index 0 followed immediately by export_progress at index 1
        root = self.w.main_widget.layout()
        self.assertTrue(root.itemAt(0).widget() is self.w.title_bar or root.itemAt(0).layout() is not None, "Index 0 must be title_bar or controls layout")
        self.assertIs(root.itemAt(1).widget(), self.w.export_progress, "Index 1 must be export_progress")
        self.assertFalse(any('Podgląd eksportu' in (w.text() if hasattr(w, 'text') else '') for w in self.w.findChildren(object)))

    def test_export_preview_auto_enter_and_exit(self):
        """Verify export preview auto-enter and auto-exit lifecycle."""
        self.assertEqual(self.w.preview_stack.currentIndex(), 0)
        pipe = self.w.enter_export_preview_mode()
        self.assertTrue(pipe)
        self.assertEqual(self.w.preview_stack.currentIndex(), 1)
        self.assertTrue(self.w.export_preview.server.isListening())

        self.w.exit_export_preview_mode()
        self.assertEqual(self.w.preview_stack.currentIndex(), 0)
        self.assertFalse(self.w.export_preview.server.isListening())

    def test_export_cancel_restores_normal_preview(self):
        """Verify cancel restores normal dual-player preview."""
        self.w.enter_export_preview_mode()
        self.assertEqual(self.w.preview_stack.currentIndex(), 1)
        with patch.object(QMessageBox, 'information'):
            self.w._cancel_export()
        self.assertEqual(self.w.preview_stack.currentIndex(), 0)

    def test_cancel_stops_live_process_and_shows_local_notification(self):
        self.w._active_backend = 'legacy'
        self.w._is_exporting = True
        self.w._cancel_requested = False
        self.w._export_clicked_at = time.perf_counter()
        self.w.enter_export_preview_mode()
        with patch.object(QMessageBox, 'information') as local_notice:
            self.w._start_export_process(sys.executable, ['-c', 'import sys; sys.stdin.readline()'])
            self.pump(lambda:self.w._export_process.state() == QProcess.Running)
            process = self.w._export_process
            self.w._cancel_export()
            self.pump(lambda:not self.w._is_exporting)
        self.assertEqual(process.state(), QProcess.NotRunning)
        self.assertEqual(self.w.preview_stack.currentIndex(), 0)
        local_notice.assert_called_once()

    def test_export_error_restores_normal_preview(self):
        """Verify export failure/error restores normal dual-player preview."""
        self.w.enter_export_preview_mode()
        self.assertEqual(self.w.preview_stack.currentIndex(), 1)
        with patch.object(QMessageBox, 'critical'):
            self.w._on_export_finished(1, QProcess.CrashExit)
        self.assertEqual(self.w.preview_stack.currentIndex(), 0)

    def test_export_success_restores_normal_preview(self):
        """Verify export success restores normal dual-player preview."""
        self.w.enter_export_preview_mode()
        self.assertEqual(self.w.preview_stack.currentIndex(), 1)
        with patch.object(QMessageBox, 'information'):
            self.w._on_export_finished(0, QProcess.NormalExit)
        self.assertEqual(self.w.preview_stack.currentIndex(), 0)

    def test_preview_fifo_failure_is_success_only_after_ffprobe_validation(self):
        import main
        self.w._active_backend = 'legacy'
        self.w._backend_selected = 'NVIDIA_MODERN_FFMPEG'
        self.w._export_out_path = str(self._media_paths[0] if self._media_paths else Path(self._media_dir.name) / 'tone440.mp4')
        self.w._export_expected_size = (3840, 2160)
        self.w._export_duration = 10.0
        self.w._export_log = ('[vost#1:0/mjpeg] Error submitting a packet to the muxer: Error number -10054 occurred\n'
                              '[out#1/fifo] Error muxing a packet\nframe=300\nprogress=end\n')
        self.w._cancel_requested = False
        self.w._is_exporting = True
        completed = subprocess.CompletedProcess([], 0, json.dumps({
            'format': {'duration': '10.0'},
            'streams': [{'codec_type': 'video', 'codec_name': 'hevc', 'width': 3840,
                         'height': 2160, 'nb_frames': '300', 'avg_frame_rate': '30/1'}],
        }), '')
        with patch('video_encoder.resolve_legacy_ffprobe', return_value='ffprobe'), \
             patch.object(main.subprocess, 'run', return_value=completed), \
             patch.object(QMessageBox, 'critical') as error, \
             patch.object(QMessageBox, 'information') as success:
            self.w._on_export_finished(4294957242, QProcess.NormalExit)
            self.pump(lambda:not self.w._preview_failure_validation_pending and not self.w._is_exporting)
        self.assertFalse(error.called)
        self.assertTrue(success.called)

    def test_main_muxer_error_is_not_misclassified_as_preview_failure(self):
        import main
        self.w._active_backend = 'legacy'
        self.w._export_log = ('[out#1/fifo] Error muxing a packet\n[out#0/mp4] Error writing trailer\n'
                              'frame=300\nprogress=end\n')
        self.w._cancel_requested = False
        with patch.object(QMessageBox, 'critical') as error:
            self.w._on_export_finished(1, QProcess.CrashExit)
        self.assertTrue(error.called)
        self.assertFalse(self.w._preview_failure_validation_pending)

    def test_ntfy_is_absent_from_application_modules(self):
        import main
        import options_dialog
        self.assertFalse(hasattr(main, 'send_notification_async'))
        self.assertFalse(hasattr(self.w, '_notify_terminal_once'))
        self.assertFalse(hasattr(self.w, '_schedule_success_notification'))
        self.assertFalse(hasattr(options_dialog.OptionsDialog, 'notificationTestFinished'))

    def test_options_forces_aspect_preserving_preview_and_has_no_ntfy_controls(self):
        from options_dialog import OptionsDialog
        dialog = OptionsDialog(self.w)
        self.assertFalse(hasattr(dialog, 'cmb_preview_scaling'))
        self.assertTrue(dialog.chk_export_preview.isChecked())
        self.assertFalse(hasattr(dialog, 'grp_notifications'))
        self.assertFalse(hasattr(dialog, 'chk_ntfy'))
        self.assertFalse(hasattr(dialog, 'edit_ntfy_server'))
        self.assertFalse(hasattr(dialog, 'edit_ntfy_topic'))
        self.assertFalse(hasattr(dialog, 'btn_ntfy_test'))
        dialog.close()

if __name__=='__main__':unittest.main()
