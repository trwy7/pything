"""Provider for all music related things, an example of an advanced app"""
from flask import render_template
from init import App, socket
from .types import playback

app = App("Music", [])

@app.on("get")
@playback.on_update
def send_song(_=None):
    app.send(
        "song",
        {
            "title": playback.song.title,
            "album": playback.song.album.title,
            "artists": ", ".join([a.name for a in playback.song.artists]),
            "art": playback.song.album.art
        } if playback.song else None
    )

@playback.on_update
def playback_listener():
    app.logger.debug("Got playback update: %s", playback.song.title if playback.song else "None")
    socket.emit("music", [
        ((playback.position / playback.song.duration) * 100) if playback.song and playback.position else None,
        playback.playing
    ])

@app.blueprint.route("/launch")
def launch():
    return render_template(f"{app.dirname}/pages/playing.html")
