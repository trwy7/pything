"""Provider for all music related things, an example of an advanced app"""
from init import App
from .types import playback, Playback

app = App("Music provider", [])

@playback.on_update
def playback_listener(pb: Playback):
    app.logger.debug("Got playback update: %s", pb.song.title if pb.song else "None")
