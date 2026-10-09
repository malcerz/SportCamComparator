from dataclasses import dataclass


@dataclass
class TelemetrySample:
    timestamp: float
    iso: int | None
    exposure: str | None


class TelemetryProvider:

    def __init__(self):
        self.samples = []

    def get_at(self, seconds: float):

        if not self.samples:
            return None

        closest = min(
            self.samples,
            key=lambda x: abs(x.timestamp - seconds)
        )

        return closest