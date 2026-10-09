"""Run with a real MP4 path; prints measured phases and 15 representative samples."""
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from telemetry_dji import DJITelemetry

if __name__ == '__main__':
    start = time.perf_counter()
    telemetry = DJITelemetry(sys.argv[1])
    elapsed = time.perf_counter() - start
    n = len(telemetry.samples)
    indices = list(range(min(5, n))) + list(range(n // 2, min(n, n // 2 + 5))) + list(range(max(0, n - 5), n))
    output = {
        'benchmark': telemetry.benchmark, 'total_seconds': elapsed,
        'model': telemetry.camera_name, 'protocol': telemetry.protocol,
        'track_id': telemetry.track_id, 'track_index': telemetry.track_index,
        'handler': telemetry.handler, 'samples': n,
        'start_datetime': telemetry.get_datetime_at(0).isoformat() if telemetry.get_datetime_at(0) else None,
        'time_range': [telemetry.timestamps[0], telemetry.timestamps[-1]],
        'rows': [{'index': i, 'timestamp': telemetry.samples[i].timestamp,
                  'iso': telemetry.samples[i].iso, 'exposure': telemetry.samples[i].exposure,
                  'offset': telemetry.sample_offsets[i], 'size': telemetry.sample_sizes[i]}
                 for i in indices],
    }
    print(json.dumps(output, indent=2))
