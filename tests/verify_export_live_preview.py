"""Real native/Qt IPC, frame equivalence, failure and paired throughput diagnostics."""
import sys
import json
import time
import subprocess
from pathlib import Path
import argparse
import numpy as np
import psutil
from PIL import Image
from gpu_counter import GpuCounter
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from PySide6.QtCore import QProcess, Qt
from PySide6.QtWidgets import QApplication
from export_live_preview import ExportLivePreview

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / 'tests/artifacts/export_live_preview'
ART.mkdir(exist_ok=True)
app = QApplication.instance() or QApplication([])
app.setQuitOnLastWindowClosed(False)
base = json.loads((ROOT/'tests/artifacts/real_gopro_dji.json').read_text(encoding='utf-8'))


def run(name, preview=True, duration=25, layout='left_right', codec='hevc',
        cancel=False, failure=False, show=False, dimensions=(1280,720), backpressure=False, stall=False):
    receiver = ExportLivePreview()
    pipe = receiver.start() if preview else ''
    if show:
        receiver.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        receiver.show()
    cfg = dict(base, output=str(ART/f'{name}.mp4'), export_preview=preview,
               preview_pipe=pipe, duration_limit_seconds=duration, layout=layout,
               codec=codec, width=dimensions[0], height=dimensions[1],
               diagnostic_preview_failure=failure)
    (ART/f'{name}.json').write_text(json.dumps(cfg),encoding='utf-8')
    frames=[]
    screenshot=False
    def received(meta, jpeg):
        frames.append(meta)
        # Save all thumbnails for exact frame-index comparisons and timeline checks.
        (ART/f'{name}_frame{meta["frame"]}.jpg').write_bytes(jpeg)
        receiver.status.setText(f'kl.{meta["frame"]} | PTS {meta["pts"]:.3f}s')
    receiver.packetReceived=received
    process=QProcess()
    process.setProcessChannelMode(QProcess.MergedChannels)
    data=bytearray()
    process.readyReadStandardOutput.connect(lambda: data.extend(bytes(process.readAllStandardOutput())))
    process.start(str(ROOT/'bin/KomparatorGpuExporter.exe'),['--config',str(ART/f'{name}.json')])
    started=time.perf_counter()
    last=started
    cpu_samples=[]
    gpu_samples=[]
    gpu=GpuCounter()
    cancelled=False
    cancel_started=None
    stalled=False
    native=None
    while process.state()!=QProcess.NotRunning:
        app.processEvents()
        now=time.perf_counter()
        if native is None and process.processId():
            try: native=psutil.Process(process.processId());native.cpu_percent()
            except psutil.Error: pass
        if now-last>.2:
            if native:
                try:
                    cpu_samples.append(native.cpu_percent())
                    sample=gpu.sample(native.pid)
                    if sample: gpu_samples.append(sample)
                except psutil.Error: pass
            last=now
        if cancel and now-started>1 and not cancelled:
            cancel_started=now
            process.write(b'{"command":"cancel"}\n')
            receiver.stop()
            cancelled=True
        if backpressure and frames and receiver.socket:
            # Disconnecting the preview transport must not fail the main pipeline.
            receiver.stop()
        if stall and frames and not stalled and receiver.socket:
            receiver.socket.readyRead.disconnect(receiver._read)
            receiver.socket.setReadBufferSize(1)
            stalled=True
        if show and len(frames)>=6 and not screenshot:
            receiver._display()
            app.processEvents()
            receiver.grab().save(str(ART/f'{name}_window.png'))
            app.primaryScreen().grabWindow(0).save(str(ART/f'{name}_desktop.png'))
            screenshot=True
        if now-started>180:
            process.kill()
            raise RuntimeError('Native export timed out')
        time.sleep(.002)
    app.processEvents()
    data.extend(bytes(process.readAllStandardOutput()))
    wall=time.perf_counter()-started
    gpu.close()
    (ART/f'{name}.log').write_bytes(data)
    messages=[]
    for line in data.decode('utf-8',errors='replace').splitlines():
        try: messages.append(json.loads(line))
        except ValueError: pass
    complete=next((m for m in messages if m.get('type')=='complete'),None)
    result=dict(name=name,exit=process.exitCode(),wall_seconds=wall,
                cpu_percent_mean=float(np.mean(cpu_samples)) if cpu_samples else None,
                gpu_engine_percent_mean={k:float(np.mean([s.get(k,0.) for s in gpu_samples])) for k in {k for s in gpu_samples for k in s}},
                complete=complete,received=frames,displayed=receiver.displayed_count,
                cancel_seconds=time.perf_counter()-cancel_started if cancel_started else None,
                warning=[m for m in messages if m.get('type')=='warning'])
    (ART/f'{name}_result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    receiver.stop(); receiver.close()
    if cancel:
        assert process.exitCode()==2 and result['cancel_seconds']<2.5, result
        assert not Path(cfg['output']).exists()
    else:
        assert process.exitCode()==0 and complete, result
        assert all(complete[k]==0 for k in ('full_frame_hwdownload_count','full_frame_hwupload_count','software_frame_count'))
        if preview and not failure:
            assert frames and complete['PREVIEW_READBACK_COUNT']>0, result
            assert all(m['width']<=960 and m['height']<=540 for m in frames)
        if failure or backpressure or stall:
            assert any('PREVIEW_DISABLED_AFTER_ERROR' in m['message'] for m in result['warning']),result
    print(json.dumps({k:v for k,v in result.items() if k not in ('received','warning') }),flush=True)
    return result


def compare(name,result):
    comparisons=[]
    for target in (5,20):
        meta=min(result['received'],key=lambda m:abs(m['pts']-target))
        path=ART/f'{name}_frame{meta["frame"]}.jpg'
        # Test-only software decoding/downscale is outside the exporter/preview path.
        output=ART/f'{name}_reference{target}.png'
        subprocess.run(['ffmpeg','-v','error','-y','-i',str(ART/f'{name}.mp4'),
            '-vf',f'select=eq(n\\,{meta["frame"]}),scale={meta["width"]}:{meta["height"]}',
            '-frames:v','1',str(output)],check=True)
        a=np.asarray(Image.open(path).convert('RGB'),dtype=float)
        b=np.asarray(Image.open(output).convert('RGB'),dtype=float)
        mae=float(np.mean(np.abs(a-b)))
        corr=float(np.corrcoef(a.ravel(),b.ravel())[0,1])
        comparisons.append(dict(pts=meta['pts'],frame=meta['frame'],mae=mae,correlation=corr))
        assert mae<15 and corr>.94,comparisons
    return comparisons


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--smoke',action='store_true')
    parser.add_argument('--ab',action='store_true')
    parser.add_argument('--gui',action='store_true')
    args=parser.parse_args()
    if args.smoke:
        run('smoke',duration=3)
    elif args.ab:
        results=[]
        # Alternate ordering to expose temperature/cache/order effects.
        for index,on in enumerate((False,True,True,False)):
            results.append(run(f'ab_{index}_{"on" if on else "off"}',preview=on,duration=60,dimensions=(3840,2160)))
        off=np.mean([r['complete']['avg_fps'] for i,r in enumerate(results) if i in (0,3)])
        on=np.mean([r['complete']['avg_fps'] for i,r in enumerate(results) if i in (1,2)])
        summary=dict(off_fps=float(off),on_fps=float(on),difference_percent=float((off-on)/off*100),runs=results)
        (ART/'ab_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in summary.items() if k!='runs'}),flush=True)
    else:
        results={}
        for name,layout,codec in (('left_right','left_right','h264'),('top_bottom','top_bottom','hevc')):
            result=run(name,layout=layout,codec=codec,show=args.gui)
            result['comparison']=compare(name,result)
            results[name]=result
        results['cancel']=run('cancel',duration=60,cancel=True)
        results['failure']=run('failure',duration=3,failure=True)
        results['disconnect']=run('disconnect',duration=5,backpressure=True)
        results['stall']=run('stall',duration=5,stall=True)
        results['wide']=run('wide',duration=3,dimensions=(1920,540))
        results['tall']=run('tall',duration=3,dimensions=(540,1920),layout='top_bottom')
        (ART/'verification.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
