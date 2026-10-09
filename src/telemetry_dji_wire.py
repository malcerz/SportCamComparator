"""Minimal DJI Action protobuf decoder; independent implementation from wire spec.

Only model/protocol, frame number, ISO and rational exposure are decoded.
"""
import math
import struct
from telemetry_mp4 import TelemetryError


def varint(data, pos=0):
    if pos >= len(data):
        raise TelemetryError('Truncated protobuf varint')
    if data[pos] < 128:
        return data[pos], pos + 1
    value = 0
    for shift in range(0, 70, 7):
        if pos >= len(data):
            raise TelemetryError('Truncated protobuf varint')
        byte = data[pos]
        pos += 1
        if shift == 63 and byte > 1:
            raise TelemetryError('Protobuf varint overflow')
        value |= (byte & 127) << shift
        if byte < 128:
            return value, pos
    raise TelemetryError('Protobuf varint overflow')


def select(data, wanted):
    """Skip unknown payloads without parsing nested messages or copying them."""
    pos = 0
    result = {}
    length = len(data)
    while pos < length:
        key = data[pos]
        if key < 128:
            pos += 1
        else:
            key, pos = varint(data, pos)
        field, wire = key >> 3, key & 7
        if not field:
            raise TelemetryError('Invalid protobuf field zero')
        if wire == 0:
            if pos < length and data[pos] < 128:
                value = data[pos]
                pos += 1
            else:
                value, pos = varint(data, pos)
        elif wire == 2:
            if pos < length and data[pos] < 128:
                size = data[pos]
                pos += 1
            else:
                size, pos = varint(data, pos)
            end = pos + size
            if end > length:
                raise TelemetryError('Truncated protobuf message')
            value = data[pos:end] if field in wanted else None
            pos = end
        elif wire in (1, 5):
            end = pos + (8 if wire == 1 else 4)
            if end > length:
                raise TelemetryError('Truncated protobuf fixed field')
            value = data[pos:end] if field in wanted else None
            pos = end
        else:
            raise TelemetryError(f'Unsupported protobuf wire type {wire}')
        if field in wanted:
            result.setdefault(field, []).append((wire, value))
    return result


def message(fields, field):
    rows = fields.get(field)
    if not rows:
        return b''
    wire, value = rows[-1]
    if wire != 2:
        raise TelemetryError('Expected protobuf message')
    return value


def text(fields, field):
    return message(fields, field).decode('utf-8', 'replace')


def exposure_pair(data):
    values = []
    for wire, value in select(data, {1}).get(1, []):
        if wire == 0:
            values.append(value)
        elif wire == 2:
            pos = 0
            while pos < len(value):
                v, pos = varint(value, pos)
                values.append(v)
        else:
            raise TelemetryError('Invalid exposure wire type')
    # int32 negatives can be encoded as ten-byte sign-extended varints.
    values = [((v & 0xffffffff) ^ 0x80000000) - 0x80000000 for v in values]
    return tuple(values) if len(values) == 2 else None


def decode_sample(data):
    root = select(data, {1, 3})
    model = protocol = ''
    if 1 in root:
        header = select(message(select(message(root, 1), {1}), 1), {1, 10})
        model = text(header, 10)
        protocol = text(header, 1)
    frame = select(message(root, 3), {1, 2})
    frame_header = select(message(frame, 1), {1})
    rows = frame_header.get(1, [(0, 0)])
    frame_number = rows[-1][1] if rows[-1][0] == 0 else None
    camera = select(message(frame, 2), {3, 4})
    rows = select(message(camera, 3), {1}).get(1, [])
    iso = None
    if rows:
        wire, value = rows[-1]
        if wire != 5:
            raise TelemetryError('Expected fixed32 ISO float')
        raw = struct.unpack('<f', value)[0]
        if math.isfinite(raw) and raw > 0:
            iso = int(raw)
    pair = exposure_pair(message(camera, 4))
    exposure = None
    if pair and pair[0] > 0 and pair[1] > 0:
        exposure = pair[0] / pair[1]
    return model, protocol, frame_number, iso, exposure, pair
