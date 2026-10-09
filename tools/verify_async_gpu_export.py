"""Verify encoded pixels, MP4 timeline and identity display matrices after benchmarks."""
import argparse,json,subprocess,struct
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--dir',required=True);p.add_argument('--baseline-dir');a=p.parse_args();art=Path(a.dir).resolve()
def probe(path,packets=False):
 args=[str(ROOT/'bin/ffprobe.exe'),'-v','error','-show_streams','-show_format','-of','json']
 if packets:args += ['-select_streams','v:0','-show_packets']
 r=subprocess.run(args+[str(path)],capture_output=True,text=True,check=True);return json.loads(r.stdout)
def matrices(path):
 result=[]
 with path.open('rb') as f:
  def boxes(start,end,containers=(b'moov',b'trak')):
   pos=start
   while pos+8<=end:
    f.seek(pos);size,kind=struct.unpack('>I4s',f.read(8));header=8
    if size==1:size=struct.unpack('>Q',f.read(8))[0];header=16
    if size==0:size=end-pos
    if size<header or pos+size>end:break
    if kind in containers:boxes(pos+header,pos+size)
    elif kind==b'tkhd':
     f.seek(pos+header);version=f.read(1)[0];f.seek(pos+header+(52 if version else 40));result.append(list(struct.unpack('>9i',f.read(36))))
    pos+=size
  boxes(0,path.stat().st_size)
 return result
def frames(path):
 filt="select='eq(n,0)+eq(n,30)+eq(n,150)+eq(n,300)+eq(n,600)+eq(n,749)',scale=960:540"
 args=[str(ROOT/'bin/ffmpeg.exe'),'-hide_banner','-loglevel','error','-threads','2','-i',str(path),'-vf',filt,'-fps_mode','passthrough','-frames:v','6','-threads','1','-pix_fmt','rgb24','-f','rawvideo','pipe:1']
 r=subprocess.run(args,capture_output=True,check=True);return np.frombuffer(r.stdout,np.uint8).reshape((-1,540,960,3))
results={};identity=[65536,0,0,0,65536,0,0,0,1073741824]
for name in ['sync_quality','async_quality','pad_rotation_sync','pad_rotation_async','cancel_inflight','long_async','normal_long']:
 path=art/(name+'.mp4')
 if not path.exists():continue
 info=probe(path);packet_info=probe(path,True);video=next(s for s in info['streams'] if s['codec_type']=='video');audio=next((s for s in info['streams'] if s['codec_type']=='audio'),None);pts=[int(p['pts']) for p in packet_info['packets']];dts=[int(p['dts']) for p in packet_info['packets']]
 steps={b-a for a,b in zip(pts,pts[1:])};mx=matrices(path)
 record={'frames':len(pts),'PTS_monotonic':all(b>a for a,b in zip(pts,pts[1:])),'DTS_monotonic':all(b>a for a,b in zip(dts,dts[1:])),'PTS_steps':sorted(steps),'start_pts':pts[0] if pts else None,'video_duration':float(video['duration']),'audio_duration':float(audio['duration']) if audio else None,'codec':video['codec_name'],'dimensions':[video['width'],video['height']],'identity_matrices':mx==[identity]*len(mx) and bool(mx),'matrix_values':mx,'rotation_metadata':video.get('side_data_list',[]),'file_bytes':path.stat().st_size}
 results[name]=record
for left,right,label in [('sync_quality','async_quality','sync_async'),('pad_rotation_sync','pad_rotation_async','pad_sync_async')]:
 if not (art/(left+'.mp4')).exists() or not (art/(right+'.mp4')).exists():continue
 one,two=frames(art/(left+'.mp4')),frames(art/(right+'.mp4'));diff=one.astype(np.float32)-two.astype(np.float32)
 results[label]={'sample_frames':len(one),'identical_pixels':bool(np.array_equal(one,two)),'MAE':float(np.abs(diff).mean()),'max_channel_difference':float(np.abs(diff).max())}
 if label=='pad_sync_async':
  black=np.concatenate([two[:,:120].reshape(-1,3),two[:,-120:].reshape(-1,3)],axis=0);results['black_padding']={'mean_rgb':black.mean(axis=0).tolist(),'p99':float(np.quantile(black,.99)),'PASS':bool(np.quantile(black,.99)<=5)}
if a.baseline_dir:
 base=Path(a.baseline_dir)/'baseline_original.mp4';target=art/'async_quality.mp4'
 if base.exists() and target.exists():
  one,two=frames(base),frames(target);diff=one.astype(np.float32)-two.astype(np.float32);results['baseline_async']={'sample_frames':len(one),'identical_pixels':bool(np.array_equal(one,two)),'MAE':float(np.abs(diff).mean()),'max_channel_difference':float(np.abs(diff).max())}
(art/'visual_timeline_verification.json').write_text(json.dumps(results,indent=2));print(json.dumps(results,indent=2))
