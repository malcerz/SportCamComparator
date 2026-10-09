# telemetry_gpmf.py

from dataclasses import dataclass
from bisect import bisect_left
from datetime import datetime, timedelta, timezone

from telemetry_gpmf_new import extract_gpmf, parse_gpmf


@dataclass
class TelemetrySample:
    timestamp: float  # seconds
    iso: int | None = None
    exposure: float | None = None  # seconds (e.g. 0.002 = 1/500)
    dt: datetime | None = None  # absolute wall-clock time (GPSU or creation_time)


class GPMFTelemetry:

    def __init__(self, filename, cancel_event=None):
        self._cancel_event = cancel_event
        self.filename = filename
        self.samples = []
        self.timestamps = []
        self.camera_name = ""
        self._time_base_dt: datetime | None = None
        self._time_base_stmp: int | None = None
        self._first_stmp: int | None = None
        self._load(filename)

    # ------------------------------------------------------------------
    # GPMF extraction & parsing
    # ------------------------------------------------------------------

    def _load(self, filename):
        """Extract GPMF from the MP4 file, parse it and build time-sorted
        telemetry samples (ISO + exposure + datetime)."""
        try:
            raw = extract_gpmf(filename, cancel_event=self._cancel_event)
        except Exception as exc:
            print(f"GPMF: nie mo\u017cna ekstrahowa\u0107 danych \u2013 {exc}")
            return

        parsed = parse_gpmf(raw)

        # Extract camera name (DVNM) from the flat list
        for key, val in parsed:
            if key == "DVNM":
                if isinstance(val, (list, tuple)):
                    self.camera_name = str(val[0])
                else:
                    self.camera_name = str(val)
                break

        # Extract time base (GPSU or creation_time)
        self._time_base_dt, self._time_base_stmp = self._extract_time_base(parsed)
        if self._time_base_dt is not None:
            try:
                self._time_base_dt = self._time_base_dt.astimezone()
            except Exception:
                pass

        self.samples = self._build_samples(parsed)
        # _build_samples walks the timestamp-sorted GPMF blocks, so this index
        # keeps frame-by-frame overlay/export lookup logarithmic.
        self.timestamps = [sample.timestamp for sample in self.samples]

        # Fill in absolute datetime for each sample
        if self._time_base_dt is not None and self._first_stmp is not None:
            if self._time_base_stmp is not None:
                # GPSU-based: offset between camera STMP base and GPSU STMP
                base_offset = (self._first_stmp - self._time_base_stmp) / 1_000_000.0
                for s in self.samples:
                    s.dt = self._time_base_dt + timedelta(seconds=s.timestamp + base_offset)
            else:
                # creation_time fallback: base_dt is the video start time
                for s in self.samples:
                    s.dt = self._time_base_dt + timedelta(seconds=s.timestamp)

        print(f"GPMF: wczytano {len(self.samples)} pr\u00f3bek telemetrii "
              f"z '{filename}'  kamera: {self.camera_name}"
              + (f"  czas bazowy: {self._time_base_dt}" if self._time_base_dt else ""))

    def _extract_time_base(self, parsed):
        """Scan the flat (key, value) list for the first GPSU block.

        Returns (base_dt, base_stmp) where:
          base_dt  \u2013 absolute datetime or None
          base_stmp \u2013 STMP value (microseconds) associated with the GPSU,
                      or None if using creation_time fallback.
        """
        # Pass 1: look for GPSU in the flat list
        current_stmp: int | None = None
        for key, val in parsed:
            if key == "STMP":
                current_stmp = val
            elif key == "GPSU":
                # GPSU: (year, month, day, hour, minute, second, millisecond)
                if isinstance(val, (list, tuple)) and len(val) >= 7:
                    try:
                        year, month, day, hour, minute, sec, ms = (int(x) for x in val[:7])
                        dt = datetime(year, month, day, hour, minute, sec,
                                      ms * 1000, tzinfo=timezone.utc)
                        print(f"GPMF: znaleziono GPSU \u2013 {dt}")
                        return dt, current_stmp
                    except Exception as exc:
                        print(f"GPMF: b\u0142\u0105d parsowania GPSU \u2013 {exc}")
                        return None, None

        # Pass 2: fallback to creation_time from MP4 metadata
        creation_dt = self._get_creation_time(self.filename)
        if creation_dt is not None:
            print(f"GPMF: brak GPSU, u\u017cyto creation_time \u2013 {creation_dt}")
            return creation_dt, None

        print("GPMF: brak danych czasu absolutnego (GPSU / creation_time)")
        return None, None

    @staticmethod
    def _get_creation_time(filename: str) -> datetime | None:
        """Read creation_time from MP4 container metadata via ffprobe."""
        import json
        import subprocess
        from video_encoder import resolve_legacy_ffprobe

        try:
            p = subprocess.run(
                [resolve_legacy_ffprobe("CPU"), "-v", "error", "-show_format", "-of", "json", filename],
                capture_output=True, text=True, timeout=5,
            )
            if p.returncode != 0:
                return None
            info = json.loads(p.stdout)
            ct = info.get("format", {}).get("tags", {}).get("creation_time")
            if ct:
                return datetime.fromisoformat(
                    ct.replace("Z", "+00:00")
                ).astimezone(timezone.utc)
        except Exception:
            pass
        return None

    def _build_samples(self, parsed):
        """Walk the flat (key, value) list and pair SHUT + ISOE blocks
        that share the same STMP timestamp."""

        # Collect SHUT / ISOE blocks indexed by their STMP value.
        # STMP is in microseconds (raw int from the GPMF binary).
        shut_blocks: dict[int, tuple[int | None, list]] = {}
        isoe_blocks: dict[int, tuple[int | None, list]] = {}
        current_stmp: int | None = None
        current_tsmp: int | None = None

        for key, val in parsed:
            if key == "STMP":
                current_stmp = val
            elif key == "TSMP":
                current_tsmp = val
            elif key == "SHUT" and current_stmp is not None:
                vals = list(val) if isinstance(val, (list, tuple)) else [val]
                shut_blocks[current_stmp] = (current_tsmp, vals)
            elif key == "ISOE" and current_stmp is not None:
                vals = list(val) if isinstance(val, (list, tuple)) else [val]
                isoe_blocks[current_stmp] = (current_tsmp, vals)

        # Only keep STMP values that have BOTH SHUT and ISOE data
        common = sorted(set(shut_blocks) & set(isoe_blocks))
        if not common:
            print("GPMF: brak sparowanych bloków SHUT/ISOE w strumieniu")
            return []

        self._first_stmp = common[0]
        samples: list[TelemetrySample] = []

        for i, stmp in enumerate(common):
            _, shut_vals = shut_blocks[stmp]
            _, iso_vals = isoe_blocks[stmp]

            n = min(len(shut_vals), len(iso_vals))
            if n == 0:
                continue

            # Estimate the sample interval (in STMP units = microseconds)
            # from the gap to the *next* block.  Fall back to ~30 fps
            # (33333 µs) when there is only one block.
            if i + 1 < len(common):
                block_gap = common[i + 1] - stmp
            elif len(common) > 1:
                block_gap = stmp - common[i - 1]
            else:
                block_gap = 1_000_000  # assume 1 second = 30 fps

            interval_us = block_gap / n

            for j in range(n):
                ts_us = stmp + j * interval_us
                ts_sec = (ts_us - self._first_stmp) / 1_000_000.0

                exposure = shut_vals[j]
                iso = iso_vals[j]

                # SHUT may be stored as integer (microseconds) or float
                # (seconds).  Normalise to seconds.
                if isinstance(exposure, int) and exposure > 0:
                    exposure = exposure / 1_000_000.0

                samples.append(TelemetrySample(
                    timestamp=ts_sec,
                    iso=iso,
                    exposure=exposure,
                ))

        return samples

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def _format_datetime(dt: datetime | None) -> str:
        """Format a datetime to 'YYYY-MM-DD  HH:MM:SS' for overlay display."""
        if dt is None:
            return ""
        return dt.strftime("%Y-%m-%d  %H:%M:%S")

    def get_datetime_at(self, sec: float) -> datetime | None:
        """Return the absolute wall-clock datetime at a given video timestamp.

        *sec* is seconds from the start of the video (same as *get_at*).
        Returns None if no time base (GPSU / creation_time) is available.
        """
        if self._time_base_dt is None or self._first_stmp is None:
            return None
        if self._time_base_stmp is not None:
            # GPSU-based: offset between camera STMP base and GPSU STMP
            base_offset = (self._first_stmp - self._time_base_stmp) / 1_000_000.0
            return self._time_base_dt + timedelta(seconds=sec + base_offset)
        else:
            # creation_time fallback: base_dt is the video start time
            return self._time_base_dt + timedelta(seconds=sec)

    def get_at(self, sec):
        """Return the TelemetrySample whose timestamp is closest to *sec*."""
        if not self.samples:
            return TelemetrySample(timestamp=sec)
        index = bisect_left(self.timestamps, sec)
        if index == 0:
            return self.samples[0]
        if index == len(self.samples):
            return self.samples[-1]
        # The former min() returned the earlier item on an exact tie; keep
        # that behavior while reducing a lookup from O(N) to O(log N).
        if sec - self.timestamps[index - 1] <= self.timestamps[index] - sec:
            index -= 1
        return self.samples[index]

    def get_overlay_text(self, sec):
        """Format telemetry as a short overlay string.

        Display order: DATETIME, TIME, ISO, EXP (exposure as a fraction, e.g. 1/500).
        """
        sample = self.get_at(sec)

        if sample.iso is None and sample.exposure is None:
            return "Brak danych telemetrii"

        # --- format exposure as a fraction ---
        exp_str = ""
        if sample.exposure is not None and sample.exposure > 0:
            fraction = int(round(1.0 / sample.exposure))
            # Clamp unrealistic values (e.g. exposure nearing zero)
            if fraction < 1:
                fraction = 1
            exp_str = f"1/{fraction}"
        else:
            exp_str = "N/A"

        # Optional camera name on the first line
        cam_line = f"{self.camera_name}\n" if self.camera_name else ""

        # Optional datetime line
        dt_line = ""
        if sample.dt is not None:
            dt_line = f"{self._format_datetime(sample.dt)}\n"

        return (
            f"{cam_line}"
            f"{dt_line}"
            f"TIME : {sec:.3f}s\n"
            f"ISO  : {sample.iso}\n"
            f"EXP  : {exp_str}"
        )

    # ------------------------------------------------------------------
    # ASS subtitle generation (for ffmpeg export)
    # ------------------------------------------------------------------

    def generate_ass(self, duration_sec: float, fps: float = 29.97,
                     progress_callback=None, font_scale: float = 1.0, opacity: float = 1.0) -> str:
        """Generate an ASS subtitle file content that burns the telemetry
        overlay into the video.  One subtitle event per video frame.

        If *progress_callback* is given, it is called as
        ``progress_callback(current_frame, total_frames)`` so the UI can
        display a preparation progress.
        """
        if not self.samples:
            if progress_callback:
                progress_callback(100, 100)
            return ""

        effective_font_size = max(8, int(round(16 * font_scale)))
        outline_px = max(1, min(4, int(round(2 * font_scale))))
        alpha_byte = int(round((1.0 - max(0.0, min(1.0, opacity))) * 255))
        primary_col = f"&H{alpha_byte:02X}FFFFFF"
        outline_col = f"&H{alpha_byte:02X}000000"
        back_col = "&HFF000000"

        lines = []
        lines.append("[Script Info]")
        lines.append("Title: Comparator telemetry overlay")
        lines.append("ScriptType: v4.00+")
        lines.append("PlayResX: 960")
        lines.append("PlayResY: 540")
        lines.append("")
        lines.append("[V4+ Styles]")
        lines.append("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour,"
                     " OutlineColour, BackColour, Bold, Italic, Underline,"
                     " StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle,"
                     " Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding")
        lines.append(
            f"Style: Telemetry,Consolas,{effective_font_size},{primary_col},&H000000FF,{outline_col},"
            f"{back_col},1,0,0,0,100,100,0,0,1,{outline_px},0,7,10,10,10,1"
        )
        lines.append("")
        lines.append("[Events]")
        lines.append("Format: Layer, Start, End, Style, Name,"
                     " MarginL, MarginR, MarginV, Effect, Text")

        n_frames = int(duration_sec * fps)
        for i in range(n_frames):
            t = i / fps
            if t > duration_sec:
                break
            text = self.get_overlay_text(t).replace("\n", "\\N")
            start = self._fmt_ass_time(t)
            end = self._fmt_ass_time(t + 1.0 / fps)
            lines.append(
                f"Dialogue: 0,{start},{end},Telemetry,,0,0,0,,{text}"
            )

            if progress_callback and i % 100 == 0:
                progress_callback(i, n_frames)

        if progress_callback:
            progress_callback(n_frames, n_frames)

        return "\n".join(lines)

    @staticmethod
    def _fmt_ass_time(sec: float) -> str:
        """Format seconds to ASS time H:MM:SS.cc (centiseconds)."""
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        cs = int((sec - int(sec)) * 100)
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"
