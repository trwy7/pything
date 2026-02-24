from typing import Literal
from collections.abc import Callable # why cant this be in typing :(
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
    def __init__(self, platform: str, id: str, title: str, album: Album, artists: list[Artist], duration: int):
        self.platform = platform
        self.id = id
        self.title = title
        self.album = album
        self.artists = artists
        self.duration = duration
class Playback:
    def __init__(self):
        self.song: Song | None = None
        self.paused: bool | None = None
        self.position: int | None = None
        self.listener: Callable | None = None
    def update(self, song: Song, paused: bool | None, position: int | None):
        self.song = song
        self.paused = paused
        self.position = position
        if isinstance(self.listener, Callable):
            self.listener(self)
    def reset(self):
        self.song = None
        self.paused = None
        self.position = None
        if isinstance(self.listener, Callable):
            self.listener(self)

playback = Playback()