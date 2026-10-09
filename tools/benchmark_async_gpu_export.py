"""Reproducible native D3D11/NVENC developer benchmarks; GUI options stay unchanged.
Usage: python tools/benchmark_async_gpu_export.py --config work/real.json --output-dir work/async_verification
Requires the project's Python dependencies. Never overwrites the supplied config/output.
"""
import argparse,json,os,sys,time
from pathlib import Path
import psutil
from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
from export_live_preview import ExportLivePreview
from gpu_counter import GpuCounter
parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);parser.add_argument('--output-dir',required=True);parser.add_argument('--long-seconds',type=float,default=360);parser.add_argument('--quick',action='store_true');parser.add_argument('--baseline-exe');parser.add_argument('--validation-only',action='store_true');parser.add_argument('--normal-only',action='store_true');args=parser.parse_args()
art=Path(args.output_dir).resolve();art.mkdir(parents=True,exist_ok=True)
os.environ['PATH']=str(ROOT/'bin')+os.pathsep+os.environ['PATH']
base=json.loads(Path(args.config).read_text(encoding='utf-8'));app=QApplication.instance() or QApplication([]);app.setQuitOnLastWindowClosed(False)
class DedicatedMemoryCounter(GpuCounter):
    def __init__(self):
        import ctypes as c
        super().__init__();self.close()
        self.available=self.api.PdhOpenQueryW(None,0,c.byref(self.query))==0
        if self.available:self.available=self.api.PdhAddEnglishCounterW(self.query,r'\GPU Process Memory(*)\Dedicated Usage',0,c.byref(self.counter))==0
        if self.available:self.api.PdhCollectQueryData(self.query)
results=[]
def run(name,mode='ASYNC',depth=4,preset='quality',preview=True,duration=25,cancel=False,pad=False,exe=None,profile=True):
    receiver=ExportLivePreview();pipe=receiver.start() if preview else '';thumbs=[]
    receiver.packetReceived=lambda meta,jpeg: thumbs.append(meta)
    cfg=dict(base,output=str(art/(name+'.mp4')),preview_pipe=pipe,export_preview=preview,encoder='nvenc',encoder_preset=preset,bitrate=50000000,duration_limit_seconds=duration)
    if pad:cfg.update(width=1920,height=1080,pad_to_4k=True,offset_seconds=-1.123,layout='top_bottom')
    config=art/(name+'.json');config.write_text(json.dumps(cfg),encoding='utf-8')
    os.environ['EXPORT_DIRECT_NVENC']='1';os.environ['PIPELINE_MODE']=mode;os.environ['NVENC_RING_DEPTH']=str(depth);
    if profile:os.environ['EXPORT_PROFILE']=str(art/name)
    else:os.environ.pop('EXPORT_PROFILE',None)
    proc=QProcess();proc.setProcessChannelMode(QProcess.MergedChannels);data=bytearray()
    proc.readyReadStandardOutput.connect(lambda:data.extend(bytes(proc.readAllStandardOutput())))
    started=time.perf_counter();proc.start(str(exe or ROOT/'bin/KomparatorGpuExporter.exe'),['--config',str(config)])
    gpu=GpuCounter();dedicated=DedicatedMemoryCounter();stats=[];threads={};cpu=[];native=None;last=0;sent_cancel=False
    while proc.state()!=QProcess.NotRunning:
        app.processEvents();now=time.perf_counter()
        if native is None and proc.processId():
            try:native=psutil.Process(proc.processId());native.cpu_percent()
            except psutil.Error:pass
        if native and now-last>=.25:
            try:
                sample=gpu.sample(native.pid);dedicated_sample=dedicated.sample(native.pid);cpu.append(native.cpu_percent());memory=native.memory_info();io=native.io_counters()
                stats.append({'elapsed':now-started,'engines':sample,'rss':memory.rss,'gpu_dedicated_bytes':sum(dedicated_sample.values()) if dedicated_sample else None,'write_bytes':io.write_bytes})
                threads.update({t.id:t.user_time+t.system_time for t in native.threads()})
            except psutil.Error:pass
            last=now
        if cancel and now-started>3 and not sent_cancel:proc.write(b'{"command":"cancel"}\n');sent_cancel=True
        if now-started>max(90,duration*3):proc.kill();raise RuntimeError('Native exporter timeout: '+name)
        time.sleep(.002)
    data.extend(bytes(proc.readAllStandardOutput()));wall=time.perf_counter()-started;receiver.stop();gpu.close();dedicated.close()
    text=data.decode('utf-8',errors='replace');(art/(name+'.log')).write_text(text,encoding='utf-8')
    packets=[]
    for line in text.splitlines():
        try:packets.append(json.loads(line))
        except ValueError:pass
    final=next((p for p in reversed(packets) if p.get('type') in ['complete','cancelled','error']),None)
    record={'name':name,'mode':mode,'depth':depth,'preset':preset,'preview':preview,'wall':wall,'exit':proc.exitCode(),'result':final,'cpu_percent_one_core_avg':sum(cpu)/max(1,len(cpu)),'max_thread_cpu_percent':max(threads.values(),default=0)*100/wall,'threads':sorted(threads.items(),key=lambda x:-x[1])[:10],'stats':stats,'thumbnails':thumbs}
    results.append(record);(art/'results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    print(name,proc.exitCode(),final.get('avg_fps') if final else None,'thumbnails',len(thumbs),flush=True)
    if proc.exitCode()!=(2 if cancel else 0):raise RuntimeError('Native export failed: '+name+' '+str(final))
    if not final or any(final.get(k,1)!=0 for k in ['full_frame_hwdownload_count','full_frame_hwupload_count','software_frame_count']):raise RuntimeError('Zero-copy gate failed: '+name)
    if preview and not thumbs:raise RuntimeError('Preview not active: '+name)
    return record
if args.normal_only:
    run('normal_long',duration=args.long_seconds,profile=False)
    sys.exit(0)
if args.baseline_exe:run('baseline_original',exe=Path(args.baseline_exe).resolve())
run('sync_quality',mode='SYNC',depth=1)
run('async_quality')
if not args.quick:
    if not args.validation_only:
        for depth in [1,2,3,6,8,12]:run('depth_'+str(depth),depth=depth)
        for preset in ['speed','balanced']:
            run('sync_'+preset,mode='SYNC',depth=1,preset=preset)
            run('async_'+preset,preset=preset)
    run('preview_off',preview=False)
    run('preview_on')
    run('pad_rotation_sync',mode='SYNC',pad=True)
    run('pad_rotation_async',pad=True)
    os.environ['NVENC_DISABLE_ASYNC_EVENTS']='1'
    run('fallback_sync_api')
    os.environ.pop('NVENC_DISABLE_ASYNC_EVENTS',None)
    run('cancel_inflight',duration=120,cancel=True)
    run('long_async',duration=args.long_seconds)
