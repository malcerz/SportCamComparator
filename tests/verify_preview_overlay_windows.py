"""Real Windows screen/pixel test, followed by five minutes of playback.

No QWidget.isVisible-only pass: camera glyph masks are checked on the actual
Windows desktop once a second. The test window stays on top only during QA.
"""
import os,sys,time,json
from pathlib import Path
os.environ.pop('QT_QPA_PLATFORM',None)
os.environ.pop('KOMPARATOR_DEBUG_OVERLAY',None)
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import numpy as np
from PySide6.QtCore import QTimer,QUrl,Qt,QPoint,QObject
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from PySide6.QtMultimedia import QMediaPlayer
from main import MainWindow
from telemetry_factory import create_telemetry

ART=Path('tests/artifacts/preview_overlay');ART.mkdir(parents=True,exist_ok=True)
app=QApplication([])
# Window-state/flag transitions in the screenshot stages can destroy/recreate
# the platform window; that must not be interpreted as completed QA.
app.setQuitOnLastWindowClosed(False)
class VisibilityWindow(MainWindow):
 def closeEvent(self,event):
  super().closeEvent(event)
  if not completed:app.exit(1)
w=VisibilityWindow();w.resize(1400,800)
w.setWindowFlag(Qt.WindowStaysOnTopHint,True)
paths=['D:/GoPro/GX010338.MP4','D:/GoPro/DJI_20261002062647_0003_D.MP4']
for i,path in enumerate(paths,1):
 setattr(w,f'telemetry{i}',create_telemetry(path));getattr(w,f'player{i}').setSource(QUrl.fromLocalFile(path))
w._manual_offset=True;w._sync_offset_ms=4423;sync=w._preview_sync;sync.set_offset(4423)
w.show();w.raise_();w.activateWindow()
players=(w.player1,w.player2);frames=[0,0];stalls=[0,0];seeks=[0,0]
for i,p in enumerate(players):
 p.video_item.videoSink().videoFrameChanged.connect(lambda frame,i=i:frames.__setitem__(i,frames[i]+1))
 p.player.mediaStatusChanged.connect(lambda status,i=i:stalls.__setitem__(i,stalls[i]+int(status==QMediaPlayer.StalledMedia)))
 original=p.set_position
 def seek(t,i=i,original=original):seeks[i]+=1;original(t)
 p.set_position=seek

def rgb(image):
 image=image.convertToFormat(QImage.Format_RGBA8888)
 return np.frombuffer(image.constBits(),dtype=np.uint8).reshape(image.height(),image.bytesPerLine())[:,:image.width()*4].reshape(image.height(),image.width(),4)[:,:,:3].copy()

def screen_crop(player,image,first_line=False):
 rect=player.overlay_rect;origin=player.video_widget.mapToGlobal(QPoint(0,0));ratio=image.devicePixelRatio()
 # QML text starts at the known padding; the camera line never changes.
 padding=player.overlay.property('padding');text=player._scene.findChild(QObject,'telemetryText')
 height=text.property('implicitHeight')/5 if first_line else rect.height()-2*padding
 x=int(round((origin.x()+rect.x()+padding)*ratio));y=int(round((origin.y()+rect.y()+padding)*ratio))
 width=int(round((rect.width()-2*padding)*ratio));height=int(round(height*ratio))
 return rgb(image.toImage())[y:y+height,x:x+width]

def framebuffer_crop(player,first_line=False):
 image=player.video_widget.grabFramebuffer()
 rect=player.overlay_rect;ratio=image.devicePixelRatio()
 padding=player.overlay.property('padding');text=player._scene.findChild(QObject,'telemetryText')
 height=text.property('implicitHeight')/5 if first_line else rect.height()-2*padding
 x=int(round((rect.x()+padding)*ratio));y=int(round((rect.y()+padding)*ratio))
 width=int(round((rect.width()-2*padding)*ratio));height=int(round(height*ratio))
 return rgb(image)[y:y+height,x:x+width]

def screenshot(name):
 desktop=app.primaryScreen().grabWindow(0);desktop.save(str(ART/(name+'_desktop.png')))
 origin=w.mapToGlobal(QPoint(0,0));r=desktop.devicePixelRatio()
 desktop.copy(int(origin.x()*r),int(origin.y()*r),int(w.width()*r),int(w.height()*r)).save(str(ART/(name+'_window.png')))
 for i,p in enumerate(players,1):p.video_widget.grabFramebuffer().save(str(ART/(name+f'_player{i}.png')))
 return desktop

stages=[('lr_t0',0,'normal',0),('lr_t5570',5570,'normal',0),('lr_t60',60000,'normal',0),
        ('top_bottom',5570,'normal',1),('resized',5570,'resize',0),('maximized',5570,'max',0),('fullscreen',5570,'full',1),('red_probe',5570,'red',0)]
step=0;phase='load';settle=0;started=None;baseline=None;samples=[];masks=None;last_text=None;pixel_failures=[];point_results=[]
last_log=-30
completed=False

def measure():
 global step,phase,settle,started,baseline,masks,last_text,last_log,completed
 try:
  if phase=='load':
   if not all(p.player.duration()>0 and not p.actual_video_rect.isEmpty() for p in players):return
   phase='points';settle=time.perf_counter()-2
  if phase=='points':
   if time.perf_counter()-settle<1:return
   if step<len(stages):
    name,target,size,orientation=stages[step]
    if not name.endswith('_capture'):
     sync.pause()
     w.layout_mode.setCurrentIndex(orientation)
     if size=='max':w.showMaximized()
     elif size=='full':w.showFullScreen()
     else:w.showNormal();w.resize(1240,600) if size=='resize' else w.resize(1400,800)
     for i,p in enumerate(players,1):
      p.set_position(target);p._scene.setProperty('diagnosticRed',size=='red')
     stages[step]=(name+'_capture',target,size,orientation)
     settle=time.perf_counter();return
    name=name.removesuffix('_capture')
    for i,p in enumerate(players,1):
     expected=getattr(w,f'telemetry{i}').get_overlay_text(target/1000)
     p.set_overlay(expected)
     assert all(part in expected for part in ('TIME :','ISO  :','EXP  :','2026-10-02'))
     assert (('MISSION 1' if i==1 else 'DJI Osmo Action 6') in expected)
     assert p.actual_video_rect.contains(p.overlay_rect), (name,p.actual_video_rect,p.overlay_rect)
     assert p.overlay.acceptedMouseButtons()==Qt.NoButton
    image=screenshot(name)
    for i,p in enumerate(players):
     crop=screen_crop(p,image);white=(crop.min(axis=2)>150)
     assert white.sum()>80,(name,i,'text not visible on screen',int(white.sum()),crop.shape)
     if size=='red':
      assert ((crop[:,:,0]>200)&(crop[:,:,1]<50)&(crop[:,:,2]<50)).mean()>.4
    point_results.append(dict(name=name,positions=[p.position() for p in players],texts=[p._overlay_text for p in players]))
    step+=1;settle=time.perf_counter();return
   w.showNormal();w.resize(1400,800);w.layout_mode.setCurrentIndex(0)
   for p in players:p._scene.setProperty('diagnosticRed',False)
   sync.seek(0);seeks[:]=[0,0];sync.errors.clear();sync.hard_seek_count=0
   phase='stabilize';settle=time.perf_counter();return
  if phase=='stabilize':
   if time.perf_counter()-settle<1:return
   w.update_overlays();image=screenshot('five_minute_start')
   masks=[framebuffer_crop(p,True).min(axis=2)>210 for p in players]
   assert all(mask.sum()>10 for mask in masks)
   baseline=dict(layout=[p.layout_update_count for p in players],text=[p.overlay_text_update_count for p in players],raise_count=[p.overlay_raise_count for p in players])
   w.setWindowFlag(Qt.WindowStaysOnTopHint,False);w.show()
   started=time.perf_counter();last_text=[p._overlay_text for p in players];sync.play();phase='play';return
  elapsed=time.perf_counter()-started
  scores=[]
  for i,p in enumerate(players):
   crop=framebuffer_crop(p,True)
   brightness=crop.min(axis=2)
   assert brightness.shape==masks[i].shape
   # Semi-transparent video changes antialiased letter edges. Use letter
   # interiors and their contrast against nearby background, not exact RGB.
   score=float((brightness[masks[i]]>130).mean())
   background=brightness[~masks[i]]
   contrast=float(brightness[masks[i]].mean()-np.median(background))
   scores.append(dict(glyph_fraction=score,contrast=contrast))
   if score<.9 or contrast<35:
    pixel_failures.append(dict(t=elapsed,player=i+1,score=score,contrast=contrast))
    p.video_widget.grabFramebuffer().save(str(ART/f'visibility_failure_{int(elapsed)}_{i+1}.png'))
  samples.append(dict(t=elapsed,frames=list(frames),positions=[p.position() for p in players],pixel_scores=scores,text=[p._overlay_text for p in players]))
  (ART/'visibility_live.json').write_text(json.dumps(dict(seconds=elapsed,hard_seek_count=sync.hard_seek_count,pixel_failures=pixel_failures,frames=frames),indent=2))
  if elapsed-last_log>=30:
   print(f'preview {elapsed:.1f}s glyph_visibility={scores} frames={frames} hard_seeks={sync.hard_seek_count}',flush=True);last_log=elapsed
  if elapsed>=300:
   sync.pause()
   w.setWindowFlag(Qt.WindowStaysOnTopHint,True);w.show();w.raise_();app.processEvents()
   screenshot('five_minute_end')
   result=dict(points=point_results,seconds=elapsed,hard_seek_count=sync.hard_seek_count,set_position_count=seeks,
     layout_updates=[p.layout_update_count-b for p,b in zip(players,baseline['layout'])],
     overlay_text_updates=[p.overlay_text_update_count-b for p,b in zip(players,baseline['text'])],
     overlay_raise_count=[p.overlay_raise_count-b for p,b in zip(players,baseline['raise_count'])],
     pixel_visibility_failures=pixel_failures,frames=frames,stalls=stalls,
     mean_sync_error=sum(sync.errors)/len(sync.errors),max_sync_error=max(sync.errors),
     max_sample_gap=max(b['t']-a['t'] for a,b in zip(samples,samples[1:])),samples=samples)
   (ART/'windows_visibility_results.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
   assert sync.hard_seek_count==0 and seeks==[0,0] and not pixel_failures
   assert result['layout_updates']==[0,0]
   assert all(count>1400 for count in result['overlay_text_updates'])
   print(json.dumps({k:v for k,v in result.items() if k not in ('samples','points')}),flush=True)
   completed=True;w.close();app.quit()
 except Exception:
  import traceback;traceback.print_exc()
  w.close();app.exit(1)
timer=QTimer();timer.timeout.connect(measure);timer.start(1000)
code=app.exec()
if not completed:
 print('TEST INCOMPLETE: event loop ended before five-minute acceptance gate',flush=True)
 code=1
sys.exit(code)
