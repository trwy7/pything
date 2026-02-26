"""Provider for all music related things, an example of an advanced app"""
from init import App, socket
from .types import playback, Playback

app = App("Music provider", [])

@playback.on_update
def playback_listener():
    app.logger.debug("Got playback update: %s", playback.song.title if playback.song else "None")
    socket.emit("music", [
        ((playback.position / playback.song.duration) * 100) if playback.song and playback.position else None,
        playback.playing
    ])
