from datetime import datetime, timedelta
import threading
import time
import requests
from flask import request, redirect
from apps.music.types import playback, Song, Album, Artist
from init import App, StringSetting, LinkSetting, BooleanSetting, DataSetting

app = App("Spotify Music Provider", [
    BooleanSetting("enabled", "Enabled", False, False),
    StringSetting("client_id", "Client ID", "", False),
    StringSetting("client_secret", "Client Secret", "", False),
    LinkSetting("auth", "Authenticate", "", True),
    DataSetting("access_token", {"token": "", "expiry": datetime.now()}),
    DataSetting("refresh_token", "")
])

def request_new_token():
    ref = app.settings['refresh_token'].get_value() # type: ignore
    if not ref:
        app.logger.debug("Something just requested a new access token without having a refresh token")
        return
    app.logger.debug("Requesting new token")
    resp = requests.post(
        "https://accounts.spotify.com/api/token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        auth=requests.auth.HTTPBasicAuth(app.settings['client_id'].get_value(), app.settings['client_secret'].get_value()), # type: ignore
        data={
            "grant_type": "refresh_token",
            "refresh_token": ref
        }
    )

    if resp.status_code != 200:
        app.logger.error("Failed to get access token: " + resp.text)
        return False
    
    data = resp.json()

    app.settings['access_token'].set_value({ # type: ignore
        "token": data['access_token'],
        "expiry": datetime.now() + timedelta(seconds=data['expires_in'] - 5)
    })
    if 'refresh_token' in data and data['refresh_token']:
        app.settings['refresh_token'].set_value(data['refresh_token']) # type: ignore

    return True

def token_expired():
    return datetime.now() > app.settings['access_token'].get_value()['expiry'] # type: ignore

def get_endpoint(endpoint: str):
    if token_expired():
        rs = request_new_token()
        if not rs:
            return rs
    if not app.settings['access_token'].get_value()['token']: # type: ignore
        return False
    return requests.get("https://api.spotify.com" + endpoint,
        headers={"Authorization": f"Bearer {app.settings['access_token'].get_value()['token']}"} # type: ignore
    )

@app.on_setting_update
def update_auth_url():
    if (not app.settings['client_id'].get_value()) or (not app.settings['client_secret'].get_value()): # type: ignore
        app.logger.debug("Hiding auth link")
        app.settings["auth"].hidden = True
        return
    app.logger.debug("Showing auth link")
    app.settings["auth"].hidden = False
    app.settings["auth"].link = f"https://accounts.spotify.com/authorize?response_type=code&client_id={app.settings['client_id'].get_value()}&scope=user-read-playback-state&redirect_uri=http://127.0.0.1:5192/apps/spotify/callback" # type: ignore

def download_art(url: str, id: str):
    return "" #FIXME: implement

update_auth_url()

@app.blueprint.route("/callback")
def callback():
    if (not app.settings['client_id'].get_value()) or (not app.settings['client_secret'].get_value()): # type: ignore
        return "You have to add a client ID and secret first."
    if 'error' in request.args:
        return "Error: " + request.args['error']
    if 'code' not in request.args:
        return "No response code was provided"

    resp = requests.post(
        "https://accounts.spotify.com/api/token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        auth=requests.auth.HTTPBasicAuth(app.settings['client_id'].get_value(), app.settings['client_secret'].get_value()), # type: ignore
        data={
            "grant_type": "authorization_code",
            "code": request.args['code'],
            "redirect_uri": "http://127.0.0.1:5192/apps/spotify/callback"
        }
    )

    if resp.status_code != 200:
        return "Error: \n" + resp.text
    
    data = resp.json()

    app.settings['access_token'].set_value({ # type: ignore
        "token": data['access_token'],
        "expiry": datetime.now() + timedelta(seconds=data['expires_in'] - 5)
    })
    app.settings['refresh_token'].set_value(data['refresh_token']) # type: ignore

    return redirect("/settings")

def music_thread():
    while True:
        time.sleep(2)
        if not app.settings['enabled'].get_value(): # type: ignore
            continue
        rdata = get_endpoint("/v1/me/player")
        if rdata in (None, False):
            continue
        if rdata.status_code == 204:
            playback.reset()
            continue
        data = rdata.json()
        if data['item']['type'] != "track":
            playback.reset()
            continue
        song = Song(
            "spotify",
            data['item']['id'],
            data['item']['name'],
            Album(
                "spotify",
                data['item']['album']['id'],
                data['item']['album']['name'],
                [Artist('spotify', a['id'], a['name']) for a in data['item']['album']['artists']],
                download_art(data['item']['album']['images'][0]['url'], data['item']['album']['id'])
            ),
            [Artist('spotify', a['id'], a['name']) for a in data['item']['artists']],
            data['item']['duration_ms']
        )
        playback.update(
            song,
            data['is_playing'],
            data['progress_ms']
        )

threading.Thread(target=music_thread, daemon=True).start()