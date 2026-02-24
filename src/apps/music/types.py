from typing import Literal
class Artist:
    def __init__(self, platform: str, id: str, name: str):
        self.platform = platform
        self.id = id
        self.name = name
class Album:
    def __init__(self, platform: str, id: str, title: str, artists: list[Artist]):
        self.platform = platform
        self.id = id
        self.title = title
        self.artists = artists
class Song:
    def __init__(self, platform: str, id: str, title: str, album: Album, artists: list[Artist]):
        self.platform = platform
        self.id = id
        self.title = title
        self.album = album
        self.artists = artists
class Device:
    def __init__(self, name: str, type: Literal["phone", "computer", "unknown"]):
        self.name = name
        self.type = type
class Playback:
    def __init__(self, song: Song | None=None, device: Device | None=None):
        self.song = song
        self.device = device
    def update(self, song: Song, device: Device):
        self.song = song
        self.device = device
    def reset(self):
        self.song = None
        self.device = None

playback = Playback()