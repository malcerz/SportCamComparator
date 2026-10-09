"""Optional real-file compatibility check; does not change the GPMF parser."""
import sys,time,json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from telemetry_gpmf_new import extract_gpmf_ffmpeg,extract_gpmf,parse_gpmf
from telemetry_gpmf import GPMFTelemetry
path=sys.argv[1] if len(sys.argv)>1 else 'D:/GoPro/GX010338.MP4'
t=time.perf_counter();old=extract_gpmf_ffmpeg(path);oldtime=time.perf_counter()-t
t=time.perf_counter();new=extract_gpmf(path);newtime=time.perf_counter()-t
assert old==new and parse_gpmf(old)==parse_gpmf(new)
with patch('telemetry_gpmf.extract_gpmf',return_value=old):a=GPMFTelemetry(path)
b=GPMFTelemetry(path)
assert a.samples==b.samples and a.camera_name==b.camera_name
points=[0,1,5.57,60,300,1000]
assert all(a.get_overlay_text(t)==b.get_overlay_text(t) for t in points)
print(json.dumps(dict(bytes_old=len(old),bytes_native=len(new),old_seconds=oldtime,native_seconds=newtime,samples=len(b.samples),all_fields_identical=True)))
