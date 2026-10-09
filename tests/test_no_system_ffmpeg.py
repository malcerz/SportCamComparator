import os
import shutil
import pytest
from pathlib import Path
from video_encoder import resolve_legacy_ffmpeg

def test_resolve_legacy_ffmpeg_compiled_no_path(monkeypatch):
    # Simulate compiled environment
    monkeypatch.setattr("video_encoder.is_compiled", lambda: True)
    
    # Hide system ffmpeg by setting PATH to empty
    monkeypatch.setenv("PATH", "")
    
    exe = resolve_legacy_ffmpeg("CPU")
    
    # It should resolve to the bundled one, regardless of PATH
    # The path should look like dist/SportCamComparator/bin/ffmpeg.exe
    assert "ffmpeg.exe" in exe
    assert "bin" in exe
    
    # If it falls back to 'ffmpeg' (which means system path), it would just be 'ffmpeg'
    assert exe != "ffmpeg"
    assert os.path.isabs(exe), f"Path should be absolute, got: {exe}"
