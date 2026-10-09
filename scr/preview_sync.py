"""Shared monotonic timeline. Only explicit seeks and sustained failures seek."""
import os
from PySide6.QtCore import QElapsedTimer


def delays(offset):
    return max(0, -offset), max(0, offset)


class PreviewSync:
    def __init__(self, players):
        self.players = players
        self.offset = 0
        self.position = 0
        self.clock = QElapsedTimer()
        self.playing = False
        self.states = [None, None]
        self.bad = [0, 0]
        self.last_seek = [-10000, -10000]
        self.hard_seek_count = 0
        self.errors = []
        self.debug = os.getenv('KOMPARATOR_DEBUG_SYNC') == '1'
        self.last_debug = -1000

    def duration(self):
        return max((d + p.player.duration() for d, p in zip(delays(self.offset), self.players)), default=0)

    def current(self):
        return min(self.duration(), self.position + (self.clock.elapsed() if self.playing else 0))

    def pause(self):
        self.position = self.current()
        self.playing = False
        for p in self.players:
            p.pause()
            p.player.setPlaybackRate(1.0)
        self.states = [None, None]

    def play(self):
        if self.current() >= self.duration():
            self.seek(0)
        self.clock.start()
        self.playing = True
        self.states = [None, None]
        self.tick()

    def seek(self, position):
        was_playing = self.playing
        self.pause()
        self.position = max(0, min(position, self.duration()))
        for p, delay in zip(self.players, delays(self.offset)):
            p.set_position(max(0, min(p.player.duration(), self.position - delay)))
        self.bad = [0, 0]
        if was_playing:
            self.play()

    def set_offset(self, offset, position=None, seek=True):
        was_playing = self.playing
        self.pause()
        self.offset = offset
        if position is not None:
            self.position = position
        if seek:
            self.seek(self.position)
        if was_playing:
            self.play()

    def tick(self):
        if not self.playing:
            return
        if self.duration() <= 0:
            return
        t = self.current()
        values = []
        for i, (p, delay) in enumerate(zip(self.players, delays(self.offset))):
            duration = p.player.duration()
            target = max(0, min(duration, t - delay))
            state = 'before' if t < delay else ('after' if t >= delay + duration else 'active')
            if state != self.states[i]:
                p.play() if state == 'active' else p.pause()
                p.player.setPlaybackRate(1.0)
                self.states[i] = state
            error = target - p.position()
            rate = p.player.playbackRate()
            if state == 'active':
                self.errors.append(abs(error))
                if len(self.errors) > 10000:
                    del self.errors[:5000]
                desired = 1.0 if abs(error) < 60 else ((1.02 if error > 0 else .98) if abs(error) < 250 else (1.05 if error > 0 else .95))
                # Keep existing correction around the lower threshold (hysteresis).
                if 60 <= abs(error) < 85 and rate == 1.0:
                    desired = 1.0
                if desired != rate:
                    p.player.setPlaybackRate(desired)
                self.bad[i] = self.bad[i] + 1 if abs(error) > 1500 else 0
                if self.bad[i] >= 8 and t - self.last_seek[i] >= 5000:
                    p.set_position(int(target))
                    self.hard_seek_count += 1
                    self.last_seek[i] = t
                    self.bad[i] = 0
            values.append(f'P{i+1} actual={p.position()} target={target} error={error} rate={p.player.playbackRate():.2f}')
        if self.debug and t - self.last_debug >= 1000:
            print(f'GLOBAL t={t} ' + ' '.join(values) + f' hard_seek_count={self.hard_seek_count}')
            self.last_debug = t
        if t >= self.duration():
            self.pause()
