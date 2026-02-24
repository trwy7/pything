"""Provider for all music related things, an example of an advanced app"""
from init import App
from .types import playback, Playback

app = App("Music provider", [])

def playback_listener(pb: Playback):
    app.logger.debug("Got playback update")

playback.listener = playback_listener