import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import benchmark_nvidia_modern as benchmark


def test_reference_command_is_handwritten_and_matches_requested_graph():
    argv = benchmark.reference_command("ffmpeg.exe", "GX.MP4", "DJI.MP4")
    assert argv[:4] == ["ffmpeg.exe", "-hide_banner", "-benchmark", "-stats"]
    assert argv[argv.index("-i") + 1] == "GX.MP4"
    assert argv[argv.index("-i", argv.index("-i") + 1) + 1] == "DJI.MP4"
    graph = argv[argv.index("-filter_complex") + 1]
    assert graph == (
        "[0:v]scale_cuda=1920:1080:format=nv12,hwdownload,format=nv12[v0];"
        "[1:v]scale_cuda=1920:1080:format=nv12,hwdownload,format=nv12[v1];"
        "[v0][v1]vstack=inputs=2:shortest=1[out]"
    )
    assert argv[argv.index("-map") + 1] == "[out]"
    assert argv[argv.index("-preset") + 1] == "p4"
    assert "-an" in argv and "-fps_mode" in argv and "passthrough" in argv
    assert not any(token in argv for token in ("setpts", "tpad", "trim", "pad", "ass"))


def test_frame_and_time_limits_are_inserted_before_null_muxer():
    original = benchmark.reference_command("ffmpeg.exe", "GX.MP4", "DJI.MP4")
    assert benchmark.add_limit(original, None, None) == original
    for limited in (benchmark.add_limit(original, 3000, None), benchmark.add_limit(original, None, 25)):
        muxer_index = limited.index("-f")
        assert limited[muxer_index:muxer_index + 3] == ["-f", "null", "NUL"]
        assert "-frames:v" not in limited or limited.index("-frames:v") < muxer_index
        assert "-t" not in limited or limited.index("-t") < muxer_index


def test_ffmpeg_benchmark_stats_are_parsed_separately_from_wallclock():
    log = (
        "frame= 3000 fps=220 q=28 speed=7.34x elapsed=0:00:13.63\r\n"
        "bench: utime=50.1s stime=1.2s rtime=13.616s\r\nbench: maxrss=3443712KiB"
    )
    stats = benchmark._stats(log)
    assert stats["ffmpeg_reported_frames"] == 3000
    assert stats["ffmpeg_reported_fps"] == 220
    assert stats["ffmpeg_reported_speed"] == 7.34
    assert stats["ffmpeg_elapsed_seconds"] == 13.616
    assert stats["peak_rss_mib"] == 3363.0


def test_dual_reference_includes_forced_split_and_full_resolution_graph():
    argv = benchmark.reference_command("ffmpeg.exe", "GX.MP4", "DJI.MP4", dual4k=True)
    graph = argv[argv.index("-filter_complex") + 1]
    assert "scale_cuda=format=nv12,hwdownload,format=nv12" in graph
    assert "vstack=inputs=2:shortest=1[out]" in graph
    assert argv[argv.index("-split_encode_mode") + 1] == "forced"
