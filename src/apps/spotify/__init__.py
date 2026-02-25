import base64
import requests
from flask import request
from apps.music.types import playback
from init import App, StringSetting, LinkSetting, DataSetting

app = App("Spotify Music Provider", [
    StringSetting("client_id", "", "", "", False),
    StringSetting("client_secret", "", "", "", False),
    LinkSetting("auth", "Authenticate", "", True),
    DataSetting("access_token", {"token": "", "expiry": 0}),
    DataSetting("refresh_token", "")
])

def update_auth_url():
    if (not app.settings['client_id'].get_value()) or (not app.settings['client_secret'].get_value()): # type: ignore
        app.settings["auth"].hidden = True
    app.settings["auth"].hidden = False
    app.settings["auth"].link = f"https://accounts.spotify.com/authorize?response_type=code&client_id={app.settings['client_id'].get_value()}&scope=user-read-playback-state&redirect_uri=http://127.0.0.1:5192/apps/spotify/callback" # type: ignore

update_auth_url()

@app.blueprint.route("/callback")
def callback():
    if (not app.settings['client_id'].get_value()) or (not app.settings['client_secret'].get_value()): # type: ignore
        return "You have to add a client ID and secret first."
    if 'error' in request.args:
        return "Error: " + request.args['error']
    if 'code' not in request.args:
        return "No response code was provided"

    resp = requests.get(
        "https://api.spotify.com/api/token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        auth=requests.auth.HTTPBasicAuth(app.settings['client_id'].get_value(), app.settings['client_secret'].get_value()), # type: ignore
        data={
            "grant_type": "authorization_code",
            "code": request.args['code'],
            "redirect_uri": "http://127.0.0.1:5192/apps/spotify/callback"
        }
    )

    