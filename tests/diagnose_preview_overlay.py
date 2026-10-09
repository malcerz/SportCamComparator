"""Capture the real Windows desktop, including Qt's native video surface."""
import os,sys,time
from pathlib import Path
os.environ['KOMPARATOR_DEBUG_OVERLAY']='1'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from PySide6.QtWidgets import QApplication,QWidget
from PySide6.QtCore import QTimer,QUrl,Qt
from PySide6.QtGui import QWindow
from main import MainWindow
from telemetry_factory import create_telemetry
app=QApplication([])
w=MainWindow();w.resize(1400,800);w.setWindowFlag(Qt.WindowStaysOnTopHint,True)
paths=['D:/GoPro/GX010338.MP4','D:/GoPro/DJI_20261002062647_0003_D.MP4']
for i,path in enumerate(paths,1):
 setattr(w,f'telemetry{i}',create_telemetry(path))
 getattr(w,f'player{i}').setSource(QUrl.fromLocalFile(path))
w._manual_offset=True;w._sync_offset_ms=0;w._preview_sync.set_offset(0)
w.show();w.raise_();w.activateWindow()
start=time.perf_counter();playing=False
folder=Path('tests/artifacts/preview_overlay')
prefix=os.getenv('KOMPARATOR_CAPTURE_PREFIX','baseline')
def capture():
 global playing
 if not playing and all(p.player.duration()>0 for p in (w.player1,w.player2)):
  w._preview_sync.play();playing=True
 if time.perf_counter()-start<7:return
 for i,p in enumerate((w.player1,w.player2),1):
  p.video_widget.grabFramebuffer().save(str(folder/(prefix+f"_player{i}.png")))
 screenshot=app.primaryScreen().grabWindow(0)
 screenshot.save(str(folder/(prefix+'_desktop.png')))
 origin=w.mapToGlobal(w.rect().topLeft());ratio=screenshot.devicePixelRatio()
 screenshot.copy(int(origin.x()*ratio),int(origin.y()*ratio),int(w.width()*ratio),int(w.height()*ratio)).save(str(folder/(prefix+'_window.png')))
 for i,p in enumerate((w.player1,w.player2),1):
  print(f'PLAYER_{i} WINDOWS: '+repr([(type(c).__name__,c.objectName(),c.geometry()) for c in p.video_widget.findChildren(QWindow)]),flush=True)
  print(f'PLAYER_{i} CHILDREN: '+repr([(type(c).__name__,c.objectName(),c.testAttribute(__import__('PySide6.QtCore',fromlist=['Qt']).Qt.WA_NativeWindow)) for c in p.video_widget.findChildren(QWidget)]),flush=True)
 w._preview_sync.pause();w.close();app.quit()
timer=QTimer();timer.timeout.connect(capture);timer.start(200)
sys.exit(app.exec())
