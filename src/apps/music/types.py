from typing import Literal
from collections.abc import Callable # why cant this be in typing :(
class Artist:
    def __init__(self, name: str):
        self.name = name
class Album:
    def __init__(self, title: str, artists: list[Artist], art: str):
        """Represents an album

        Args:
            title (str): _description_
            artists (list[Artist]): A list of artists that have worked on the album
            art (str): A relative url to the album art of the album, must be relative to / on this server, e.x. /apps/music/image.png
        """
        self.title = title
        self.artists = artists
        self.art = art
class Song:
    def __init__(self, title: str, album: Album, artists: list[Artist], duration: int):
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