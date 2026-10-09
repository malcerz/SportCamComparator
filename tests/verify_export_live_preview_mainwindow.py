"""Exercise the production MainWindow export button, preparation and QProcess."""
import sys
import json
import time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import QApplication, QMessageBox
from main import MainWindow
from telemetry_factory import create_telemetry
import export_prepare

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'tests/artifacts/export_live_preview'
base=json.loads((ROOT/'tests/artifacts/real_gopro_dji.json').read_text(encoding='utf-8'))
app=QApplication([])
app.setQuitOnLastWindowClosed(False)
original=export_prepare.prepare_export


def diagnostic_prepare(options,providers,directory):
    result=original(options,providers,directory)
    config=Path(result[2][1])
    cfg=json.loads(config.read_text(encoding='utf-8'))
    kind=Path(options['output']).stem
    cfg['duration_limit_seconds']=3 if kind.endswith(('off','failure')) else (60 if kind.endswith('cancel') else 25)
    cfg['diagnostic_preview_failure']=kind.endswith('failure')
    config.write_text(json.dumps(cfg),encoding='utf-8')
    (ART/(Path(options['output']).stem+'_config.json')).write_text(json.dumps(cfg),encoding='utf-8')
    return result


results={}
for layout in ('left_right','top_bottom','cancel','failure'):
    window=MainWindow()
    window.setWindowFlag(Qt.WindowStaysOnTopHint,True)
    window.resize(1250,720)
    window.telemetry1=create_telemetry(base['video1'])
    window.telemetry2=create_telemetry(base['video2'])
    window.player1.setSource(QUrl.fromLocalFile(base['video1']))
    window.player2.setSource(QUrl.fromLocalFile(base['video2']))
    window.encoder_combo.setCurrentText('AMD AMF')
    window.backend_combo.setCurrentIndex(1)
    window.scale_combo.setCurrentText('x1')
    window.codec_combo.setCurrentText('H.265')
    window.audio_combo.setCurrentIndex(3)
    window._sync_offset_ms=4423
    window.splitter.setOrientation(Qt.Horizontal if layout=='left_right' else Qt.Vertical)
    window.show()
    window.export_preview.setWindowFlag(Qt.WindowStaysOnTopHint,True)
    output=ART/f'mainwindow_{layout}.mp4'
    count=[]
    captured=False
    cancel_started=None
    def received(meta,jpeg): count.append(meta)
    window.export_preview.packetReceived=received
    with patch('main.QFileDialog.getSaveFileName',return_value=(str(output),'')), \
         patch.object(export_prepare,'prepare_export',diagnostic_prepare), \
         patch.object(QMessageBox,'information'), patch.object(QMessageBox,'critical') as error:
        window.btn_export.click()
        started=time.monotonic()
        while window._is_exporting and time.monotonic()-started<180:
            app.processEvents()
            if layout=='cancel' and len(count)>=3 and cancel_started is None:
                cancel_started=time.monotonic()
                window._cancel_export()
            if len(count)>=6 and not captured:
                window.export_preview._display()
                app.processEvents()
                window.grab().save(str(ART/f'mainwindow_{layout}_main.png'))
                window.export_preview.grab().save(str(ART/f'mainwindow_{layout}_preview.png'))
                app.primaryScreen().grabWindow(0).save(str(ART/f'mainwindow_{layout}_desktop.png'))
                captured=True
            time.sleep(.005)
        assert not window._is_exporting,'MainWindow export timeout'
        assert not error.called,error.call_args
        if layout=='cancel':
            assert cancel_started and time.monotonic()-cancel_started<2.5
            assert not output.exists()
        else:
            assert window._last_gpu_metrics['status']=='success'
            if layout in ('left_right','top_bottom'): assert count and captured
            if layout=='failure': assert 'PREVIEW_DISABLED_AFTER_ERROR' in window._export_log
        print(layout,'PASS',flush=True)
        results[layout]=dict(metrics=window._last_gpu_metrics,packets=len(count),
                            displayed=window.export_preview.displayed_count,
                            start_latency=window._export_start_latency,
                            cancel_seconds=time.monotonic()-cancel_started if cancel_started else None)
    window.export_preview.close()
    window.close()
    window.deleteLater()
    app.processEvents()
(ART/'mainwindow_verification.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
print(json.dumps(results),flush=True)
