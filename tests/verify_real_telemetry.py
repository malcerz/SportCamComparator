"""Optional integration check: python tests/verify_real_telemetry.py DJI.mp4 GoPro.mp4."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from telemetry_factory import create_telemetry
from telemetry_dji import DJITelemetry
from telemetry_gpmf import GPMFTelemetry

for filename in sys.argv[1:]:
    telemetry = create_telemetry(filename)
    assert telemetry.samples, filename
    ass = telemetry.generate_ass(2, fps=30000/1001)
    assert 'Dialogue:' in ass
    if isinstance(telemetry, DJITelemetry):
        assert any(s.iso is not None for s in telemetry.samples)
        assert any(s.exposure is not None for s in telemetry.samples)
        assert telemetry.get_datetime_at(0) is not None
    elif isinstance(telemetry, GPMFTelemetry):
        baseline = GPMFTelemetry(filename)
        assert telemetry.samples == baseline.samples
        assert ass == baseline.generate_ass(2, fps=30000/1001)
        for sec in [0, 1, 10, 60, 300]:
            assert telemetry.get_overlay_text(sec) == baseline.get_overlay_text(sec)
    print(filename, type(telemetry).__name__, len(telemetry.samples), 'OK')
