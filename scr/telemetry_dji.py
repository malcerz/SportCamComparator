"""Native, sparse MP4/protobuf reader for DJI Osmo Action 4/5/6."""
from bisect import bisect_left
from datetime import timedelta
import time
from telemetry_mp4 import MP4Metadata, TelemetryError, table
from telemetry_dji_wire import decode_sample
from telemetry_gpmf import GPMFTelemetry, TelemetrySample


class DJITelemetry:
    generate_ass = GPMFTelemetry.generate_ass
    _fmt_ass_time = staticmethod(GPMFTelemetry._fmt_ass_time)

    def __init__(self, filename, metadata=None, cancel_event=None):
        started = time.perf_counter()
        self.filename = str(filename)
        self.samples = []
        self.timestamps = []
        self.camera_name = 'DJI Osmo Action'
        self.protocol = ''
        self._base_dt = None
        metadata = metadata or MP4Metadata(filename)
        track = next((t for t in metadata.tracks if t.codec == b'djmd'), None)
        if track is None:
            raise TelemetryError('Nie znaleziono tracku djmd.')
        self.track_id = track.track_id
        self.track_index = track.index
        self.handler = track.handler
        self._base_dt = metadata.created or track.created
        self.duration = metadata.duration / metadata.timescale
        offsets, sizes, timestamps, table_seconds = metadata.sample_table(track)
        self.sample_offsets = offsets
        self.sample_sizes = sizes
        intervals = table(track.stbl[b'stts'], 8, '>II')
        delta = max(intervals, key=lambda row: row[0])[1] if intervals else 0
        self.fps = track.timescale / delta if delta else None
        read_seconds = parse_seconds = 0.0
        malformed = 0
        with open(filename, 'rb', buffering=0) as file:
            for i, (offset, size, ts) in enumerate(zip(offsets, sizes, timestamps)):
                if cancel_event is not None and cancel_event.is_set():
                    raise TelemetryError('Anulowano odczyt telemetrii DJI.')
                start = time.perf_counter()
                file.seek(offset)
                data = file.read(size)
                read_seconds += time.perf_counter() - start
                if len(data) != size:
                    raise TelemetryError('Niepełna próbka tracku djmd.')
                start = time.perf_counter()
                try:
                    model, protocol, _, iso, exposure, _ = decode_sample(data)
                except TelemetryError:
                    malformed += 1
                    iso = exposure = None
                    model = protocol = ''
                parse_seconds += time.perf_counter() - start
                if protocol:
                    if protocol not in ('dvtm_ac203.proto', 'dvtm_ac204.proto', 'dvtm_ac206.proto'):
                        raise TelemetryError(f'Nieobsługiwany protokół DJI: {protocol}')
                    self.protocol = protocol
                if model:
                    self.camera_name = {
                        'DJI OsmoAction4': 'DJI Osmo Action 4',
                        'DJI OsmoAction5 Pro': 'DJI Osmo Action 5 Pro',
                        'DJI OsmoAction5Pro': 'DJI Osmo Action 5 Pro',
                        'DJI OsmoAction6': 'DJI Osmo Action 6',
                    }.get(model, model)
                self.samples.append(TelemetrySample(ts, iso, exposure,
                    self._base_dt + timedelta(seconds=ts) if self._base_dt else None))
        if not self.protocol:
            raise TelemetryError('Brak rozpoznanego schematu DJI Action w clip metadata.')
        if not self.samples or malformed == len(self.samples):
            raise TelemetryError('Brak poprawnych próbek djmd.')
        self.samples.sort(key=lambda sample: sample.timestamp)
        self.timestamps = [sample.timestamp for sample in self.samples]
        self.benchmark = {
            'file_size': metadata.file_size,
            'detect_seconds': metadata.detect_seconds,
            'table_seconds': table_seconds,
            'read_seconds': read_seconds,
            'protobuf_seconds': parse_seconds,
            'provider_seconds': time.perf_counter() - started,
            'bytes_read': metadata.bytes_read + sum(sizes),
            'metadata_bytes': sum(sizes),
            'malformed_samples': malformed,
        }
        print(f'DJI native: model={self.camera_name}, protocol={self.protocol}, '
              f'track={self.track_id} ({self.handler}), samples={len(self.samples)}, '
              f'time={self.timestamps[0]:.3f}..{self.timestamps[-1]:.3f}s, '
              f'benchmark={self.benchmark}')

    def get_at(self, sec):
        if not self.samples:
            return TelemetrySample(sec)
        index = bisect_left(self.timestamps, sec)
        if index == len(self.samples):
            index -= 1
        elif index and sec - self.timestamps[index-1] <= self.timestamps[index] - sec:
            index -= 1
        return self.samples[index]

    def get_datetime_at(self, sec):
        return self._base_dt + timedelta(seconds=sec) if self._base_dt else None

    def get_overlay_text(self, sec):
        sample = self.get_at(sec)
        lines = [self.camera_name]
        if sample.dt is not None:
            lines.append(sample.dt.strftime('%Y-%m-%d  %H:%M:%S'))
        lines.append(f'TIME : {sec:.3f}s')
        if sample.iso is not None:
            lines.append(f'ISO  : {sample.iso}')
        if sample.exposure is not None and sample.exposure > 0:
            lines.append(f'EXP  : 1/{max(1, round(1 / sample.exposure))}')
        return '\n'.join(lines)
