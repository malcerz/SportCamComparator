"""Small, seek-based ISO-BMFF reader for classic (non-fragmented) MP4 tracks.

mdat is skipped by size. Only moov and selected metadata sample ranges are read.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os
import struct
import time


class TelemetryError(RuntimeError):
    pass


def boxes(data, start=0, end=None):
    end = len(data) if end is None else end
    while start < end:
        if end - start < 8:
            raise TelemetryError('Truncated MP4 box header')
        size, tag = struct.unpack_from('>I4s', data, start)
        header = 8
        if size == 1:
            if end - start < 16:
                raise TelemetryError('Truncated extended MP4 box header')
            size = struct.unpack_from('>Q', data, start + 8)[0]
            header = 16
        elif size == 0:
            size = end - start
        if size < header or start + size > end:
            raise TelemetryError('Invalid MP4 box bounds')
        yield tag, start + header, start + size
        start += size


def children(data):
    return {tag: data[start:end] for tag, start, end in boxes(data)}


def clock_header(data):
    if len(data) < 20:
        raise TelemetryError('Truncated MP4 clock header')
    if data[0] == 0:
        created, _, scale, duration = struct.unpack_from('>IIII', data, 4)
    elif data[0] == 1 and len(data) >= 32:
        created, _, scale, duration = struct.unpack_from('>QQIQ', data, 4)
    else:
        raise TelemetryError('Unsupported MP4 clock header')
    if not scale:
        raise TelemetryError('Zero MP4 timescale')
    dt = None
    if created:
        try:
            dt = (datetime(1904, 1, 1, tzinfo=timezone.utc) +
                  timedelta(seconds=created)).astimezone()
        except (OverflowError, ValueError):
            pass
    return dt, scale, duration


def table(data, width, fmt):
    if len(data) < 8:
        raise TelemetryError('Truncated MP4 sample table')
    count = struct.unpack_from('>I', data, 4)[0]
    if len(data) != 8 + count * width:
        raise TelemetryError('Invalid MP4 sample table size')
    return list(struct.iter_unpack(fmt, data[8:]))


@dataclass
class Track:
    index: int
    track_id: int
    codec: bytes
    handler: str
    created: object
    timescale: int
    duration: int
    stbl: dict
    edits: bytes | None


class MP4Metadata:
    def __init__(self, filename):
        start = time.perf_counter()
        self.filename = str(filename)
        self.file_size = os.path.getsize(filename)
        self.bytes_read = 0
        self.mdat_ranges = []
        moov = None
        with open(filename, 'rb', buffering=0) as file:
            offset = 0
            while offset < self.file_size:
                file.seek(offset)
                raw = file.read(8)
                self.bytes_read += len(raw)
                if len(raw) != 8:
                    raise TelemetryError('Truncated MP4 header')
                size, tag = struct.unpack('>I4s', raw)
                header = 8
                if size == 1:
                    raw = file.read(8)
                    self.bytes_read += len(raw)
                    if len(raw) != 8:
                        raise TelemetryError('Truncated extended MP4 header')
                    size = struct.unpack('>Q', raw)[0]
                    header = 16
                elif size == 0:
                    size = self.file_size - offset
                if size < header or offset + size > self.file_size:
                    raise TelemetryError('Invalid MP4 top-level box bounds')
                if tag == b'moof':
                    raise TelemetryError('Fragmented MP4 telemetry is not supported')
                if tag == b'mdat':
                    self.mdat_ranges.append((offset + header, offset + size))
                if tag == b'moov':
                    if size - header > 64 * 1024 * 1024:
                        raise TelemetryError('MP4 moov exceeds 64 MiB limit')
                    self.moov_offset = offset
                    moov = file.read(size - header)
                    self.bytes_read += len(moov)
                offset += size
        if moov is None:
            raise TelemetryError('MP4 moov not found')
        top = children(moov)
        self.created, self.timescale, self.duration = clock_header(top[b'mvhd'])
        self.tracks = []
        for tag, begin, end in boxes(moov):
            if tag != b'trak':
                continue
            trak = children(moov[begin:end])
            mdia = children(trak[b'mdia'])
            minf = children(mdia[b'minf'])
            if b'stbl' not in minf:
                continue
            stbl = children(minf[b'stbl'])
            stsd = stbl.get(b'stsd', b'')
            if len(stsd) < 8:
                raise TelemetryError('Invalid stsd')
            entries = list(boxes(stsd, 8))
            if not entries:
                continue
            codec = entries[0][0]
            tkhd = trak[b'tkhd']
            track_id = struct.unpack_from('>I', tkhd, 20 if tkhd[0] else 12)[0]
            created, scale, duration = clock_header(mdia[b'mdhd'])
            handler = mdia[b'hdlr'][24:].split(b'\0', 1)[0].decode('utf-8', 'replace')
            edits = children(trak[b'edts']).get(b'elst') if b'edts' in trak else None
            self.tracks.append(Track(len(self.tracks), track_id, codec, handler,
                                     created, scale, duration, stbl, edits))
        self.detect_seconds = time.perf_counter() - start

    def sample_table(self, track):
        start = time.perf_counter()
        stbl = track.stbl
        stsz = stbl[b'stsz']
        if len(stsz) < 12:
            raise TelemetryError('Truncated stsz')
        default, count = struct.unpack_from('>II', stsz, 4)
        if count > 10_000_000:
            raise TelemetryError('Too many metadata samples')
        if default:
            sizes = [default] * count
        else:
            if len(stsz) != 12 + 4 * count:
                raise TelemetryError('Invalid stsz sample count')
            sizes = [v[0] for v in struct.iter_unpack('>I', stsz[12:])]
        chunks = table(stbl[b'co64'], 8, '>Q') if b'co64' in stbl else table(stbl[b'stco'], 4, '>I')
        mapping = table(stbl[b'stsc'], 12, '>III')
        if not mapping or mapping[0][0] != 1:
            raise TelemetryError('Invalid stsc first chunk')
        if any(not n or desc != 1 for _, n, desc in mapping):
            raise TelemetryError('Unsupported stsc sample description')
        if any(mapping[i][0] >= mapping[i+1][0] for i in range(len(mapping)-1)):
            raise TelemetryError('Unordered stsc')
        offsets = []
        sample = 0
        entry = 0
        for chunk_index, (chunk_offset,) in enumerate(chunks, 1):
            while entry + 1 < len(mapping) and chunk_index >= mapping[entry+1][0]:
                entry += 1
            offset = chunk_offset
            for _ in range(mapping[entry][1]):
                if sample >= count:
                    raise TelemetryError('stsc has more samples than stsz')
                size = sizes[sample]
                if size > 1024 * 1024 or not any(a <= offset and offset + size <= b
                                                for a, b in self.mdat_ranges):
                    raise TelemetryError('Invalid metadata sample range')
                offsets.append(offset)
                offset += size
                sample += 1
        if sample != count:
            raise TelemetryError('stsc/stsz sample count mismatch')
        timestamps = []
        dts = 0
        for n, delta in table(stbl[b'stts'], 8, '>II'):
            if len(timestamps) + n > count:
                raise TelemetryError('stts sample count mismatch')
            timestamps.extend(range(dts, dts + n * delta, delta) if delta else [dts] * n)
            dts += n * delta
        if len(timestamps) != count:
            raise TelemetryError('stts sample count mismatch')
        if b'ctts' in stbl:
            ctts = stbl[b'ctts']
            if ctts[0] not in (0, 1):
                raise TelemetryError('Unsupported ctts version')
            i = 0
            for n, shift in table(ctts, 8, '>Ii' if ctts[0] else '>II'):
                if i + n > count:
                    raise TelemetryError('ctts sample count mismatch')
                for j in range(i, i+n):
                    timestamps[j] += shift
                i += n
            if i != count:
                raise TelemetryError('ctts sample count mismatch')
        # Support the usual optional empty edit followed by a unit-rate media
        # edit. Complex playlists must not silently produce incorrect times.
        offset = 0.0
        if track.edits is not None:
            edits = track.edits
            if edits[0] not in (0, 1):
                raise TelemetryError('Unsupported elst version')
            rows = table(edits, 20 if edits[0] else 12,
                         '>Qqhh' if edits[0] else '>Iihh')
            seen_media = False
            for duration, media_time, rate, fraction in rows:
                if rate != 1 or fraction:
                    raise TelemetryError('Non-unit MP4 edit rate is unsupported')
                if media_time == -1 and not seen_media:
                    offset += duration / self.timescale
                elif media_time >= 0 and not seen_media:
                    offset -= media_time / track.timescale
                    seen_media = True
                else:
                    raise TelemetryError('Complex MP4 edit list is unsupported')
        times = [t / track.timescale + offset for t in timestamps]
        return offsets, sizes, times, time.perf_counter() - start


    def read_track_payload(self, codecs=(b'gpmd', b'gpmf'), cancel_event=None):
        track = next((t for t in self.tracks if t.codec in codecs), None)
        if track is None:
            raise TelemetryError('Metadata track not found')
        offsets, sizes, _, _ = self.sample_table(track)
        payloads = []
        with open(self.filename, 'rb') as file:
            for offset, size in zip(offsets, sizes):
                if cancel_event is not None and cancel_event.is_set():
                    raise TelemetryError('Anulowano odczyt telemetrii')
                file.seek(offset)
                raw = file.read(size)
                self.bytes_read += len(raw)
                if len(raw) != size:
                    raise TelemetryError('Truncated metadata sample')
                payloads.append(raw)
        return b''.join(payloads)
