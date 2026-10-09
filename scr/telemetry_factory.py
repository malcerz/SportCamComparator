"""Provider selection from native MP4 sample descriptions."""
from telemetry_mp4 import MP4Metadata, TelemetryError
from telemetry_gpmf import GPMFTelemetry, TelemetrySample
from telemetry_dji import DJITelemetry


class NullTelemetry:
    camera_name = ''
    samples = ()

    def __init__(self, filename):
        self.filename = str(filename)

    def get_at(self, sec):
        return TelemetrySample(sec)

    def get_datetime_at(self, sec):
        return None

    def get_overlay_text(self, sec):
        return 'Brak danych telemetrii'

    def generate_ass(self, duration_sec, fps=29.97, progress_callback=None, *args, **kwargs):
        if progress_callback:
            progress_callback(100, 100)
        return ''


def create_telemetry(filename, cancel_event=None):
    if cancel_event is not None and cancel_event.is_set():
        raise TelemetryError('Anulowano odczyt telemetrii.')
    metadata = MP4Metadata(filename)
    for track in metadata.tracks:
        if track.codec in (b'gpmd', b'gpmf') or ('gopro' in track.handler.lower()
                                               and 'met' in track.handler.lower()):
            print('Telemetry: detected GoPro GPMF')
            return GPMFTelemetry(filename, cancel_event=cancel_event)
    if any(track.codec == b'djmd' for track in metadata.tracks):
        print('Telemetry: detected DJI djmd (native)')
        return DJITelemetry(filename, metadata=metadata, cancel_event=cancel_event)
    print('Telemetry: no supported telemetry stream')
    return NullTelemetry(filename)
