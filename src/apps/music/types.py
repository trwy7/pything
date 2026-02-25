from typing import Literal
from collections.abc import Callable # why cant this be in typing :(
class Artist:
    def __init__(self, platform: str, id: str, name: str):
        self.platform = platform
        self.id = id
        self.name = name
class Album:
    def __init__(self, platform: str, id: str, title: str, artists: list[Artist], art: str):
        """Represents an album

        Args:
            platform (str): The platform that the album is on, e.g. "spotify"
            id (str): A platform unique ID for the album, if the service does not provide one, make one unique enough that it will always be different than all other songs, like an SHA hash of the metadata
            title (str): The album title
            artists (list[Artist]): A list of artists for the album
            art (str): A relative url to the album art of the album, must be relative to / on this server, e.x. /apps/music/image.png
        """
        self.platform = platform
        self.id = id
        self.title = title
        self.artists = artists
        self.art = art
class Song:
    def __init__(self, platform: str, id: str, title: str, album: Album, artists: list[Artist], duration: int):
        """Represents a song

        Args:
            platform (str): The platform that the song is on, e.g. "spotify"
            id (str): A platform unique ID for the song, if the service does not provide one, make one unique enough that it will always be different than all other songs, like an SHA hash of the metadata
            title (str): The song title
            album (Album): The Album that represents the song
            artists (list[Artist]): A list of artists for the song
            duration (int): The duration of the song in milliseconds
        """
        self.platform = platform
        self.id = id
        self.title = title
        self.album = album
        self.artists = artists
        self.duration = duration
class Playback:
    def __init__(self):
        self.song: Song | None = None
        self.playing: bool | None = None
        self.position: int | None = None
        self.listener: Callable | None = None
    def update(self, song: Song, playing: bool | None, position: int | None):
        self.song = song
        self.playing = playing
        self.position = position
        if isinstance(self.listener, Callable):
            self.listener(self)
    def reset(self):
        self.song = None
        self.playing = None
        self.position = None
        if isinstance(self.listener, Callable):
            self.listener(self)

playback = Playback()