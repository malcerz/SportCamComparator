"""MainWindow click latency with two full compact telemetry tables; cancel real export."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import sys,json,time,tempfile
from datetime import datetime,timedelta
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from PySide6.QtWidgets import QApplication,QMessageBox
from main import MainWindow
from telemetry_gpmf import GPMFTelemetry,TelemetrySample
app=QApplication([]);w=MainWindow()
for i,name in enumerate(('gopro','dji'),1):
 data=json.loads(Path(f'tests/artifacts/{name}_telemetry.json').read_text(encoding='utf-8'))
 provider=GPMFTelemetry.__new__(GPMFTelemetry)
 provider.filename=['D:/GoPro/GX010338.MP4','D:/GoPro/DJI_20261002062647_0003_D.MP4'][i-1]
 provider.camera_name=data['camera'];provider._time_base_dt=datetime.fromisoformat(data['start_datetime']);provider._time_base_stmp=None;provider._first_stmp=0
 provider.samples=[TelemetrySample(t,iso,exp,provider._time_base_dt+timedelta(seconds=t)) for t,iso,exp in data['samples']]
 provider.timestamps=[s.timestamp for s in provider.samples]
 setattr(w,f'telemetry{i}',provider)
w.backend_combo.setCurrentIndex(1);w.encoder_combo.setCurrentText('AMD AMF');w.scale_combo.setCurrentText('x0.25')
w._sync_offset_ms=4423
output=str(Path('tests/artifacts/gui_full_telemetry_cancelled.mp4').resolve())
with patch('main.QFileDialog.getSaveFileName',return_value=(output,'')),patch.object(QMessageBox,'information'),patch.object(QMessageBox,'critical') as error:
 w.export_video();deadline=time.perf_counter()+20;cancelled=False;size=None;last=time.perf_counter();max_gap=0
 while w._is_exporting and time.perf_counter()<deadline:
  app.processEvents();now=time.perf_counter();max_gap=max(max_gap,now-last);last=now
  if w._export_started_at and not cancelled and now-w._export_started_at>1:
   config=Path(w._export_tmpdir)/'gpu_export_config.json';size=config.stat().st_size
   data=json.loads(config.read_text(encoding='utf-8'))
   assert 'duration_limit_seconds' not in data
   assert isinstance(data['telemetry1'],dict)
   w._cancel_export();cancelled=True
  time.sleep(.005)
 assert not w._is_exporting and cancelled and not error.called,error.call_args
 assert not Path(output).exists()
 result=dict(start_latency_seconds=w._export_start_latency,config_bytes=size,max_gui_pump_gap_seconds=max_gap,native_cancel_pass=True)
 Path('tests/artifacts/gui_export_start.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
w.close()
