"""Worker-only export preparation with capability hierarchy (D3D11 -> Legacy GPU -> CPU)."""
import json
import subprocess
import sys
from pathlib import Path

import video_encoder
import nvidia_modern
from video_orientation import inspect_orientation


def probe_gpu_exporter(*args, **kwargs):
    return video_encoder.probe_gpu_exporter(*args, **kwargs)


def probe_legacy_encoder(*args, **kwargs):
    return video_encoder.probe_legacy_encoder(*args, **kwargs)


def probe_encoder_limit(*args, **kwargs):
    return video_encoder.probe_encoder_limit(*args, **kwargs)


def resolve_export_helper(*args, **kwargs):
    return video_encoder.resolve_export_helper(*args, **kwargs)


def resolve_legacy_ffmpeg(*args, **kwargs):
    return video_encoder.resolve_legacy_ffmpeg(*args, **kwargs)


def resolve_legacy_ffprobe(*args, **kwargs):
    return video_encoder.resolve_legacy_ffprobe(*args, **kwargs)



def _normalize_probe_result(res):
    if isinstance(res, tuple):
        if len(res) == 2:
            return res[0], res[1], {}
        if len(res) >= 3:
            return res[0], res[1], res[2]
    return False, str(res), {}


def compact_telemetry(provider):
    dt = provider.get_datetime_at(0)
    return {
        'camera': provider.camera_name,
        'start_datetime': dt.isoformat() if dt else '',
        'samples': [[s.timestamp, s.iso, s.exposure] for s in provider.samples],
    }


def prepare_export(options, providers, directory):
    p1, p2 = providers
    playback_speed = int(options.get('playback_speed', 1))
    if playback_speed not in (1, 2, 4):
        raise RuntimeError("Przyspieszenie musi wynosić ×1, ×2 albo ×4.")
    dual4k = bool(options.get('dual_4k', False))
    pad_to_16_9 = bool(options.get('pad_to_16_9', options.get('pad_to_4k', True)))
    layout = options.get('layout', 'left_right')
    if dual4k:
        content_width, content_height = ((7680, 2160) if layout == 'left_right' else (3840, 4320))
    else:
        content_width, content_height = ((3840, 1080) if layout == 'left_right' else (1920, 2160))
    if not dual4k and not pad_to_16_9:
        width, height = (3840, 1080) if layout == 'left_right' else (1920, 2160)
    else:
        width, height = 3840, 2160
    hw = options['hw']  # 'AMD AMF', 'Intel QSV', 'NVIDIA', 'CPU'
    backend_mode = options['backend']  # 0 = AUTO, 1 = Forced D3D11, 2 = Forced Legacy

    encoder_short = {
        'NVIDIA': 'nvenc',
        'AMD AMF': 'amf',
        'Intel QSV': 'qsv',
        'CPU': 'cpu',
    }.get(hw, 'cpu')

    preset_map = {
        'Najszybszy': 'speed', 'Fastest': 'speed', 'speed': 'speed',
        'Zbalansowany': 'balanced', 'Balanced': 'balanced', 'balanced': 'balanced',
        'Najlepsza jakość': 'quality', 'Best Quality': 'quality', 'quality': 'quality',
    }
    encoder_preset = preset_map.get(options.get('preset', ''), 'balanced')
    codec = 'hevc'

    ffprobe_exe = resolve_legacy_ffprobe(hw)
    durations = []
    audio_present = []
    video_sizes = []
    fps_values = []
    orientations = []
    for provider in providers:
        res = subprocess.run(
            [ffprobe_exe, '-v', 'error', '-show_format', '-show_streams', '-of', 'json', provider.filename],
            capture_output=True, text=True, timeout=30,
        )
        if res.returncode:
            raise RuntimeError(f"Błąd analizy wideo ({provider.filename}): {res.stderr}")
        info = json.loads(res.stdout)
        durations.append(float(info['format']['duration']))
        audio_present.append(any(s['codec_type'] == 'audio' for s in info['streams']))
        video_stream = next((s for s in info['streams'] if s.get('codec_type') == 'video'), None)
        if not video_stream:
            raise RuntimeError(f"Brak strumienia wideo: {provider.filename}")
        orientation = inspect_orientation(video_stream)
        orientations.append(orientation)
        print(f"[export] INPUT_ROTATE_TAG={orientation['rotate_tag']} FILE={provider.filename}")
        print(f"[export] INPUT_DISPLAYMATRIX_ROTATION={orientation['displaymatrix_rotation']} FILE={provider.filename}")
        print(f"[export] INPUT_ORIENTATION_DECISION={orientation['decision']} FILE={provider.filename}")
        # Older callers/tests may supply reduced ffprobe payloads. The legacy
        # paths never needed dimensions here, so retain their 4K fallback.
        video_sizes.append((int(video_stream.get('width', 3840)), int(video_stream.get('height', 2160))))
        fps_values.append(_stream_fps(video_stream))

    offset = options['offset'] / 1000.0
    delays = max(0.0, -offset), max(0.0, offset)
    duration = max(d + t for d, t in zip(delays, durations))
    effective_duration = duration / playback_speed
    output_fps = min(60.0, max(1.0, max(fps_values) if fps_values else 30.0))
    print(f"[export] PLAYBACK_SPEED={playback_speed}")
    print(f"[export] OUTPUT_FPS={output_fps:g}")

    use_d3d11 = False
    helper_path = None
    backend_selected = ""
    preview_port = options.get('preview_port') if options.get('export_preview', True) else None
    modern_selected = False

    # NVIDIA Modern is considered only in AUTO. Forced D3D11 and Legacy retain
    # their established behavior. The probe decodes a real frame from input 1.
    if hw == 'NVIDIA' and backend_mode == 0:
        modern_ok, modern_detail = nvidia_modern.probe_nvidia_modern(
            resolve_legacy_ffmpeg('NVIDIA'), p1.filename, encoder_preset
        )
        print(f"[export] NVIDIA_MODERN_PROBE={'PASS' if modern_ok else 'FAIL'}")
        if not modern_ok:
            print(f"[export] NVIDIA_MODERN_PROBE_DETAIL={modern_detail}")
        if dual4k and modern_ok:
            dual_ok, dual_detail = nvidia_modern.probe_nvidia_dual4k(
                resolve_legacy_ffmpeg('NVIDIA'), options['layout'], encoder_preset, pad_to_16_9
            )
            print(f"[export] NVIDIA_DUAL4K_PROBE={'PASS' if dual_ok else 'FAIL'}")
            if not dual_ok:
                print(f"[export] NVIDIA_DUAL4K_PROBE_DETAIL={dual_detail}")
            modern_selected = dual_ok
        else:
            modern_selected = modern_ok and not dual4k

    if modern_selected:
        if video_sizes[0] != video_sizes[1]:
            raise RuntimeError("NVIDIA Modern wymaga wejść o zgodnych wymiarach obrazu.")
        if dual4k and video_sizes[0] != (3840, 2160):
            raise RuntimeError("Tryb 4K UHD na kamerę wymaga dwóch wejść 3840×2160.")
        ass_paths = [None, None]
        if options['overlay']:
            for i, provider in enumerate(providers):
                ass = Path(directory) / f'overlay{i+1}.ass'
                ass_text = provider.generate_ass(
                    durations[i],
                    font_scale=float(options.get('overlay_font_scale', 1.0)),
                    opacity=float(options.get('overlay_opacity', 1.0)),
                )
                ass.write_text(ass_text, encoding='utf-8')
                if ass_text.strip():
                    ass_paths[i] = str(ass)
        ffmpeg_exe = resolve_legacy_ffmpeg('NVIDIA')
        args, output_size = nvidia_modern.build_command(
            ffmpeg_exe=ffmpeg_exe,
            video_paths=(str(Path(p1.filename).resolve()), str(Path(p2.filename).resolve())),
            output=str(Path(options['output']).resolve()), layout=options['layout'],
            input_size=video_sizes[0], scale=1.0, dual4k=dual4k,
            preset=encoder_preset, bitrate_mbps=float(options['bitrate']), duration=duration,
            delays=delays, audio_present=tuple(audio_present), audio_mode=options['audio'],
            ass_paths=tuple(ass_paths), pad_to_16_9=pad_to_16_9, playback_speed=playback_speed,
            output_fps=output_fps,
            orientation_filters=tuple(item['filter'] for item in orientations),
            clear_output_rotation=all(item['normalized'] for item in orientations),
            preview_port=preview_port,
            preview_size=tuple(options.get('preview_size', (640, 360))),
            preview_fps=float(options.get('preview_fps', 5.0)),
        )
        backend_selected = 'NVIDIA_MODERN_FFMPEG'
        print(f"[export] EXPORT_BACKEND_SELECTED={backend_selected}")
        print("[export] NVIDIA_MODERN_PIPELINE: NVDEC -> SCALE_CUDA -> HWDOWNLOAD -> CPU_FILTERS -> STACK -> NVENC")
        if dual4k:
            print("[export] NVIDIA_DUAL4K=1")
            print("[export] NVIDIA_SPLIT_ENCODE=FORCED")
        print(f"[export] OUTPUT_SIZE={output_size[0]}x{output_size[1]}")
        print(f"[export] FFMPEG_COMMAND={nvidia_modern.command_for_log(ffmpeg_exe, args)}")
        return 'legacy', ffmpeg_exe, args, effective_duration, backend_selected

    # -------------------------------------------------------------------------
    # 1. FORCED D3D11 (backend_mode == 1)
    # -------------------------------------------------------------------------
    if backend_mode == 1 and playback_speed == 1 and not dual4k:
        if hw == 'CPU':
            raise RuntimeError("D3D11 Zero-Copy nie obsługuje CPU. Wybierz GPU (AMD, Intel, NVIDIA) lub zmień backend na Legacy.")

        helper_path, helper_err = resolve_export_helper('d3d11', hw)
        if not helper_path:
            raise RuntimeError(helper_err or f"Brak helpera D3D11 dla {hw}")

        d3d_ok, d3d_msg, d3d_diag = _normalize_probe_result(probe_gpu_exporter(encoder_short, encoder_preset, width, height, codec))
        if not d3d_ok:
            reason = (d3d_diag or {}).get('reason', 'D3D11_INIT_FAILED')
            raise RuntimeError(f"D3D11 Zero-Copy niedostępny dla {hw} [{reason}]:\n{d3d_msg}")

        use_d3d11 = True
        backend_selected = f"{hw.upper().replace(' ', '_')}_D3D11"

    # -------------------------------------------------------------------------
    # 2. AUTO (backend_mode == 0)
    # -------------------------------------------------------------------------
    elif backend_mode == 0 and playback_speed == 1 and not dual4k:
        if hw != 'CPU':
            helper_path, helper_err = resolve_export_helper('d3d11', hw)
            if helper_path:
                d3d_ok, d3d_msg, d3d_diag = _normalize_probe_result(probe_gpu_exporter(encoder_short, encoder_preset, width, height, codec))
                if d3d_ok:
                    use_d3d11 = True
                    backend_selected = f"{hw.upper().replace(' ', '_')}_D3D11"
                else:
                    reason = (d3d_diag or {}).get('reason', 'UNKNOWN')
                    print(f"[export] AUTO: D3D11 Zero-Copy niedostępny dla {hw} [{reason}]: {d3d_msg}")
                    print(f"[export] AUTO: Przejście do Próby 2 (Legacy hardware encoder)...")
            else:
                print(f"[export] AUTO: Helper GPU niedostępny ({helper_err}). Przejście do Próby 2...")

    # If D3D11 selected and verified, build GPU exporter config
    if use_d3d11 and helper_path:
        print(f"[export] EXPORT_BACKEND_SELECTED={backend_selected}")
        cfg = dict(
            video1=str(Path(p1.filename).resolve()),
            video2=str(Path(p2.filename).resolve()),
            output=str(Path(options['output']).resolve()),
            layout=options['layout'],
            offset_seconds=offset,
            # D3D11's compositor pads its raw stacked content into the final
            # 3840x2160 canvas. Keep content dimensions separate so black bars
            # are added around the whole composite instead of inside each slot.
            width=content_width,
            height=content_height,
            fps=output_fps,
            encoder=encoder_short,
            codec=codec,
            encoder_preset=encoder_preset,
            bitrate=int(options['bitrate'] * 1000000) or 20000000,
            audio=options['audio'],
            export_preview=options.get('export_preview', True),
            preview_pipe=options.get('preview_pipe', ''),
            preview_width=int(options.get('preview_size', (640, 360))[0]),
            preview_height=int(options.get('preview_size', (640, 360))[1]),
            preview_fps=5,
            show_overlay=options['overlay'],
            overlay_font_scale=float(options.get('overlay_font_scale', 1.0)),
            overlay_opacity=float(options.get('overlay_opacity', 1.0)),
            pad_to_4k=pad_to_16_9,
            telemetry1=compact_telemetry(p1) if options['overlay'] else {},
            telemetry2=compact_telemetry(p2) if options['overlay'] else {},
            input_rotation1=orientations[0]['d3d_rotation'],
            input_rotation2=orientations[1]['d3d_rotation'],
        )
        config_file = Path(directory) / 'gpu_export_config.json'
        config_file.write_text(json.dumps(cfg, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        return 'd3d11', str(helper_path), ['--config', str(config_file)], duration, backend_selected

    # -------------------------------------------------------------------------
    # 3. LEGACY HARDWARE OR CPU (Attempt 2 & Attempt 3)
    # -------------------------------------------------------------------------
    legacy_ffmpeg_exe = resolve_legacy_ffmpeg(hw)
    name = None

    if hw != 'CPU':
        # Attempt 2: Vendor Legacy Hardware Encoder
        candidate_encoder = 'hevc_' + encoder_short
        if probe_legacy_encoder(candidate_encoder, legacy_ffmpeg_exe):
            name = candidate_encoder
            backend_selected = f"{hw.upper().replace(' ', '_')}_LEGACY"
            print(f"[export] AUTO/Legacy: Wybrano sprzętowy koder {candidate_encoder} na {legacy_ffmpeg_exe}")
        else:
            print(f"[export] Koder {candidate_encoder} nie może wystartować na {legacy_ffmpeg_exe}.")

    if not name:
        # Attempt 3: CPU libx265 fallback
        cpu_ffmpeg_exe = resolve_legacy_ffmpeg('CPU')
        if probe_legacy_encoder('libx265', cpu_ffmpeg_exe):
            name = 'libx265'
            legacy_ffmpeg_exe = cpu_ffmpeg_exe
            backend_selected = 'CPU_X265'
            print(f"[export] AUTO/Legacy: Wybrano awaryjny CPU koder libx265 na {cpu_ffmpeg_exe}")
        else:
            raise RuntimeError("Wszystkie ścieżki eksportu zawiodły (D3D11 FAIL, Legacy GPU FAIL, CPU libx265 FAIL).")

    print(f"[export] EXPORT_BACKEND_SELECTED={backend_selected}")

    if dual4k:
        target_size = ((7680, 4320) if pad_to_16_9 else
                       ((7680, 2160) if options['layout'] == 'left_right' else (3840, 4320)))
    elif pad_to_16_9:
        target_size = (3840, 2160)
    else:
        target_size = (3840, 1080) if options['layout'] == 'left_right' else (1920, 2160)
    if dual4k:
        if video_sizes[0] != (3840, 2160) or video_sizes[1] != (3840, 2160):
            raise RuntimeError("Podwójne 4K wymaga dwóch wejść 3840 × 2160.")
        ok, detail = video_encoder.probe_encoder_size(name, *target_size, legacy_ffmpeg_exe)
        if not ok:
            raise RuntimeError(f"Wybrany koder {name} nie obsługuje Podwójnego 4K ({target_size[0]}×{target_size[1]}): {detail}")
    else:
        limit = probe_encoder_limit(name, legacy_ffmpeg_exe)
        if limit is None or limit[0] < target_size[0] or limit[1] < target_size[1]:
            supported = "brak" if limit is None else f"{limit[0]}×{limit[1]}"
            raise RuntimeError(
                f"Wybrany koder {name} nie obsługuje wymaganego płótna {target_size[0]}×{target_size[1]} "
                f"(maksimum z szybkiego testu: {supported}). Nie zmieniono rozdzielczości."
            )

    filters = []
    for i, (provider, delay) in enumerate(zip(providers, delays)):
        ass = Path(directory) / f'overlay{i+1}.ass'
        overlay = 'null'
        if options['overlay']:
            ass_text = provider.generate_ass(
                durations[i],
                font_scale=float(options.get('overlay_font_scale', 1.0)),
                opacity=float(options.get('overlay_opacity', 1.0))
            )
            ass.write_text(ass_text, encoding='utf-8')
            escaped = str(ass).replace('\\', '/').replace(':', '\\:')
            if ass_text.strip():
                overlay = f"ass=filename='{escaped}'"
        orientation_filter = orientations[i]['filter'] or 'null'
        if orientations[i]['filter'].startswith('transpose='):
            slot_w, slot_h = (3840, 2160) if dual4k else (1920, 1080)
            orientation_filter += (
                f',scale={slot_w}:{slot_h}:force_original_aspect_ratio=decrease:force_divisible_by=2'
                f',pad={slot_w}:{slot_h}:(ow-iw)/2:(oh-ih)/2:black'
            )
        filters.append(
            f'[{i}:v]{orientation_filter}[orient_fix{i}];[orient_fix{i}]setpts=PTS-STARTPTS,{overlay},'
            f'tpad=start_mode=clone:start_duration={delay}:stop_mode=clone:stop_duration={duration},'
            f'trim=duration={duration}[v{i}]'
        )

    stack = 'hstack' if options['layout'] == 'left_right' else 'vstack'
    if not dual4k:
        filters.append(
            "[v0]scale=1920:1080:force_original_aspect_ratio=decrease:force_divisible_by=2,"
            "pad=1920:1080:(1920-iw)/2:(1080-ih)/2:black[v0s];"
            "[v1]scale=1920:1080:force_original_aspect_ratio=decrease:force_divisible_by=2,"
            "pad=1920:1080:(1920-iw)/2:(1080-ih)/2:black[v1s]"
        )
        stack_inputs = "[v0s][v1s]"
    else:
        stack_inputs = "[v0][v1]"
    filters.append(f"{stack_inputs}{stack}=inputs=2[stacked]")
    stack_size = ((7680, 2160) if options['layout'] == 'left_right' else (3840, 4320)) if dual4k else ((3840, 1080) if options['layout'] == 'left_right' else (1920, 2160))
    final_input = "[stacked]"
    if pad_to_16_9 and stack_size != target_size:
        filters.append(f"[stacked]pad={target_size[0]}:{target_size[1]}:(ow-iw)/2:(oh-ih)/2:black[padded]")
        final_input = "[padded]"
    speed = f"(PTS-STARTPTS)/{playback_speed}" if playback_speed > 1 else "PTS-STARTPTS"
    filters.append(f"{final_input}setpts={speed},fps={output_fps:g}[vbase]")
    if preview_port:
        preview_width, preview_height = options.get('preview_size', (640, 360))
        preview_fps = float(options.get('preview_fps', 5.0))
        filters.append(f"[vbase]split=2[v][preview_source];[preview_source]fps={preview_fps:g},scale={int(preview_width)}:{int(preview_height)}:force_original_aspect_ratio=decrease,format=yuvj420p[preview]")
    else:
        filters.append("[vbase]null[v]")

    selected_audio = [
        i for i in range(2)
        if audio_present[i] and options['audio'] in (('left', 'both') if i == 0 else ('right', 'both'))
    ]
    for i in selected_audio:
        filters.append(
            f'[{i}:a]asetpts=PTS-STARTPTS,adelay={delays[i]*1000}:all=1,apad,atrim=duration={duration}[a{i}]'
        )

    if selected_audio:
        filters.append(
            ''.join(f'[a{i}]' for i in selected_audio) +
            (f'amix=inputs={len(selected_audio)}:duration=longest' if len(selected_audio) > 1 else 'anull') +
            (',atempo=2,atempo=2' if playback_speed == 4 else ',atempo=2' if playback_speed == 2 else '') +
            f',atrim=duration={effective_duration:g}[a]'
        )

    args = ['-y', '-noautorotate', '-i', p1.filename, '-noautorotate', '-i', p2.filename, '-filter_complex', ';'.join(filters), '-map', '[v]']
    if selected_audio:
        args += ['-map', '[a]', '-c:a', 'aac']
    args += ['-c:v', name]
    if name == 'libx265':
        x265_preset = {'speed': 'veryfast', 'balanced': 'medium', 'quality': 'slow'}.get(encoder_preset, 'medium')
        args += ['-preset', x265_preset]
    elif 'amf' in name:
        args += ['-quality', encoder_preset]
    elif 'nvenc' in name:
        nv_preset = {'speed': 'p2', 'balanced': 'p4', 'quality': 'p6'}.get(encoder_preset, 'p4')
        args += ['-preset', nv_preset]
    elif 'qsv' in name:
        qsv_preset = {'speed': 'faster', 'balanced': 'medium', 'quality': 'slow'}.get(encoder_preset, 'medium')
        args += ['-preset', qsv_preset]

    if options['bitrate']:
        args += ['-b:v', f"{options['bitrate']}M"]
    elif name.startswith('libx'):
        args += ['-crf', '22']

    # Ensure output rotation is 0 / upright
    args += ['-fps_mode', 'cfr', '-r', f'{output_fps:g}']
    if all(item['normalized'] for item in orientations):
        args += ['-metadata:s:v:0', 'rotate=0']
    args += ['-t', str(effective_duration), options['output']]
    if preview_port:
        args += ['-map', '[preview]', '-an', '-c:v', 'mjpeg', '-q:v', '18', '-fps_mode', 'passthrough',
                 '-f', 'fifo', '-queue_size', '2', '-drop_pkts_on_overflow', '1', '-fifo_format', 'mjpeg',
                 '-flush_packets', '1', f'tcp://127.0.0.1:{int(preview_port)}?tcp_nodelay=1']

    return 'legacy', legacy_ffmpeg_exe, args, effective_duration, backend_selected


def _stream_fps(stream):
    from fractions import Fraction
    for key in ('avg_frame_rate', 'r_frame_rate'):
        try:
            fps = float(Fraction(stream.get(key, '0/0')))
            if 1 <= fps <= 240:
                return fps
        except (TypeError, ValueError, ZeroDivisionError):
            continue
    return 30.0
