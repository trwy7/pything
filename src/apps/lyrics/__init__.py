from flask import render_template
from init import App
from apps.music.types import playback

app = App("Lyrics", [])

@app.blueprint.route("/launch")
def launch():
    return render_template(f"{app.dirname}/pages/lyrics.html")
