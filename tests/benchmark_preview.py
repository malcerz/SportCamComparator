"""Real Qt multimedia playback measurement (visible window, five minutes)."""
import sys, time, json, threading, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtMultimedia import QMediaPlayer
from main import MainWindow
from telemetry_factory import create_telemetry
import psutil
import faulthandler
trace_file=open("tests/artifacts/preview_threads.log","w")
faulthandler.dump_traceback_later(60,repeat=True,file=trace_file)
app = QApplication([])
w = MainWindow(); w.resize(1400,800); w.show()
paths = ['D:/GoPro/GX010338.MP4','D:/GoPro/DJI_20261002062647_0003_D.MP4']
for player,path in zip((w.player1,w.player2),paths): player.setSource(QUrl.fromLocalFile(path))
w._manual_offset = True; w._sync_offset_ms = 4423
sync = w._preview_sync
sync.set_offset(4423)
process = psutil.Process()
frames = [0,0]; stalls = [0,0]; seeks = [0,0]; positions = [[],[]]
for i,p in enumerate(sync.players):
    p.video_item.videoSink().videoFrameChanged.connect(lambda f,i=i: frames.__setitem__(i,frames[i]+1))
    p.player.mediaStatusChanged.connect(lambda status,i=i: stalls.__setitem__(i,stalls[i]+int(status==QMediaPlayer.StalledMedia)))
    original = p.set_position
    def seek(t,i=i,original=original):
        seeks[i]+=1; original(t)
    p.set_position = seek
samples=[]; start=None; telemetry_started=False; baseline=None

def load():
    for i,path in enumerate(paths):
        provider=create_telemetry(path)
        w._telemetry_results.put((i+1, w._telemetry_jobs[i+1], provider, None))

def measure():
    global start,telemetry_started,baseline
    if start is None:
        if not all(p.player.duration()>0 for p in sync.players):
            print('Waiting for durations:',[p.player.duration() for p in sync.players],flush=True)
            for p in sync.players:p.play()
            return
        sync.seek(0); seeks[:]=[0,0]; sync.play(); start=time.perf_counter(); baseline=[p.layout_update_count for p in sync.players]
        process.cpu_percent()
        return
    elapsed=time.perf_counter()-start
    if elapsed >= 30 and not telemetry_started:
        telemetry_started=True
        for i in (1,2): w._telemetry_jobs[i]=threading.Event()
        threading.Thread(target=load,daemon=True).start()
    if int(elapsed) % 30 == 0:
        print(f'preview t={elapsed:.1f}s frames={frames} hard_seeks={sync.hard_seek_count}',flush=True)
    samples.append(dict(t=elapsed,cpu=process.cpu_percent(),frames=list(frames),global_t=sync.current(),p=[p.position() for p in sync.players],hard_seeks=sync.hard_seek_count))
    if elapsed >= 300:
        sync.pause()
        result=dict(seconds=elapsed,hard_seek_count=sync.hard_seek_count,set_position_count=seeks,layout_updates=[p.layout_update_count-b for p,b in zip(sync.players,baseline)],
                    mean_sync_error=sum(sync.errors)/len(sync.errors) if sync.errors else None,max_sync_error=max(sync.errors,default=0),stalls=stalls,frames=frames,samples=samples)
        Path('tests/artifacts/preview_benchmark.json').write_text(json.dumps(result,indent=2))
        print(json.dumps({k:v for k,v in result.items() if k!='samples'}),flush=True)
        w.close(); app.quit()
timer=QTimer(); timer.timeout.connect(measure); timer.start(1000)
sys.exit(app.exec())
