"""Real AMD/NVENC/QSV matrix, failure gate and spectral audio verification."""
import json, subprocess, os
from pathlib import Path
import numpy as np
BASE_DIR=Path(__file__).resolve().parent
ART=BASE_DIR/'tests/artifacts'
EXE=BASE_DIR/'bin/KomparatorGpuExporter.exe'
CLIP1=ART/'tone440.mp4'
CLIP2=ART/'tone880.mp4'
ENCODER=os.environ.get('KOMPARATOR_TEST_ENCODER','amf')
RESULTS=[]

def run_case(name, **overrides):
    output=ART/(name+'.mp4')
    cfg=dict(video1=str(CLIP1),video2=str(CLIP2),output=str(output),width=1280,height=720,encoder=ENCODER,codec='h264',audio='mute',show_overlay=True,
        offset_seconds=4.423, telemetry1=dict(camera='Tone 440',start_datetime='2026-10-05T12:00:00+02:00',samples=[[0,100,.002],[4,200,.004]]),
        telemetry2=dict(camera='Tone 880',start_datetime='2026-10-05T12:00:04.423+02:00',samples=[[0,400,.001],[2,800,.005]]))
    cfg.update(overrides)
    output=Path(cfg['output'])
    config=ART/(name+'.json');config.write_text(json.dumps(cfg,ensure_ascii=False),encoding='utf-8')
    result=subprocess.run([str(EXE),'--config',str(config)],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=180)
    (ART/(name+'.log')).write_text(result.stdout+result.stderr,encoding='utf-8')
    messages=[]
    for line in (result.stdout+'\n'+result.stderr).splitlines():
        try: messages.append(json.loads(line))
        except ValueError: pass
    complete=next((m for m in messages if m.get('type')=='complete'),None)
    if cfg.get('diagnostic_fail_frame',-1)>=0 or name.startswith('failure'):
        assert result.returncode != 0 and not complete and any(m.get('type')=='error' for m in messages),result.stdout+result.stderr
        assert not output.exists(), 'Partial output remains'
        metrics=dict(name=name,exit_code=result.returncode,partial_removed=True)
    else:
        assert result.returncode==0 and complete and complete['status']=='success',result.stdout+result.stderr
        assert all(complete[k]==0 for k in ('full_frame_hwdownload_count','full_frame_hwupload_count','software_frame_count'))
        probe=subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(output)],capture_output=True,text=True,check=True)
        info=json.loads(probe.stdout)
        video=next(s for s in info['streams'] if s['codec_type']=='video')
        assert video['avg_frame_rate']=='30000/1001',video['avg_frame_rate']
        duration=float(info['format']['duration'])
        if cfg.get('duration_limit_seconds'): assert abs(duration-cfg['duration_limit_seconds'])<.15
        audio=any(s['codec_type']=='audio' for s in info['streams'])
        assert audio==(cfg['audio']!='mute')
        metrics=dict(name=name,complete=complete,duration=duration)
        if name.startswith('audio_') and audio:
            raw=subprocess.run(['ffmpeg','-v','error','-i',str(output),'-vn','-ac','1','-ar','48000','-f','f32le','-'],capture_output=True,check=True).stdout
            signal=np.frombuffer(raw,dtype='<f4')
            def amplitude(freq,start,stop):
                x=signal[int(start*48000):int(stop*48000)].astype(float)
                t=np.arange(len(x))/48000
                return abs(np.sum(x*np.exp(-2j*np.pi*freq*t)))*2/len(x)
            early=[amplitude(f,1,2) for f in (440,880)]
            late=[amplitude(f,5,6) for f in (440,880)]
            metrics.update(early_amplitudes=early,late_amplitudes=late)
            if cfg['audio']=='both': assert late[0]>.02 and late[1]>.02 and early[1]<.001
            if cfg['audio']=='left': assert late[0]>.04 and late[1]<.001
            if cfg['audio']=='right': assert late[1]>.04 and early[1]<.001 and late[0]<.001
    RESULTS.append(metrics)
    print(json.dumps(metrics),flush=True)
    (ART/'native_matrix_results.json').write_text(json.dumps(RESULTS,indent=2))
    return output

if __name__=='__main__':
    probe=subprocess.run([str(EXE),'--probe','--encoder',ENCODER,'--codec','hevc'],capture_output=True,text=True)
    assert probe.returncode==0,probe.stderr+probe.stdout
    for mode in ('mute','left','right','both'): run_case('audio_'+mode,audio=mode)
    run_case('failure_compositor',diagnostic_fail_frame=15)
    run_case('failure_encoder',encoder='unsupported_encoder')
    run_case('failure_input',video1='missing_video.mp4')
    run_case('failure_output',output=str(ART/'missing_directory'/'out.mp4'))
    run_case('hevc_vertical_negative',codec='hevc',layout='top_bottom',offset_seconds=-4.423,audio='both')
    for reverse in (False,True):
        clips=['D:/GoPro/GX010338.MP4','D:/GoPro/DJI_20261002062647_0003_D.MP4']
        telemetry=[json.loads((ART/'gopro_telemetry.json').read_text(encoding='utf-8')),json.loads((ART/'dji_telemetry.json').read_text(encoding='utf-8'))]
        if reverse: clips.reverse();telemetry.reverse()
        run_case('real_dji_gopro' if reverse else 'real_gopro_dji',video1=clips[0],video2=clips[1],telemetry1=telemetry[0],telemetry2=telemetry[1],codec='hevc',audio='both',duration_limit_seconds=10)
    run_case('hevc_4k_short',codec='hevc',width=3840,height=2160,duration_limit_seconds=3)
    print(f'EXECUTED {len(RESULTS)} CASES: PASS; encoder={ENCODER}; other vendors NOT_TESTED')
