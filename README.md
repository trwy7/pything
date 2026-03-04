# PYThing

PYThing is a python version of [DeskThing](https://github.com/ItsRiprod/DeskThing), designed to be easy to write apps for, and to be light on the client.

## Features

- Automatic carthing connection
- Easy setup
- Light on the client
- No internet is required, unless an app needs it.
- Very modular, all features that are not important to the core are within apps that can be removed/replaced easily

<details>
   <summary>
      <h2>🏃 Running</h2>
   </summary>

### Prebuilt

Go to [releases](https://github.com/trwy7/pything/releases), and download the release for your device, and run it. On linux, you may need to run `chmod +x pything-linux` before running. If you are using an ARM device, or a mac, you will need to run from source.

### From source

Clone this repo

Install dependencies with `pip install -r requirements.txt`, on linux you may need to make a virtual environment first

Run `python3 src/init.py`

## Usage

If you have a Car Thing, it should be detected automatically. If you do not, you may visit the web UI from http://127.0.0.1:5192.

All app settings can be configured from http://127.0.0.1:5192/settings. Some apps require this to work.

</details>

<details>
   <summary>
      <h2>❓ Troubleshooting</h2>
   </summary>

## Troubleshooting

### My Car Thing won't connect

Make sure you are running the custom Thing Labs firmware, if the device is not detected by the script, make sure the device shows up in ADB. You may need udev rules on linux. If it is not detected when your computer turns on, it may need to be manually unplugged and replugged.

</details>

<details>
   <summary>
      <h2>▶️ Apps</h2>
   </summary>

All apps can store data in the form of settings, you can access any visible settings from `/settings`

- Clock
    - A basic clock app
- System
    - Shows information about your computer
        - RAM
        - CPU
        - Disk
        - Network
- Music
    - App that can take input from other apps.
    - Basically, takes input from a 'provider' app, and passes that data to everything else.
    - Injects code into the client to display a playbar
- Spotify
    - A music provider app, takes data from spotify. Requires spotify premium.
    - Does not have a UI
    - Because it relies on the Spotify API, song changes will take ~2-4 seconds to show up, sometimes longer.
- Lyrics
    - An app that takes the data from the music provider, and gets the lyrics for the current song.
    - Uses LRCLIB and only requests lyrics when the app is open on at least one device
- Customizer
    - An app that provides custom colors to the UI
    - Takes broadcasts from other apps so any app can set the accent color

</details>

<details>
   <summary>
      <h2>🛠️ Making an app</h2>
   </summary>

To create a custom app, you must be using the source build. Apps have a defined structure, but not all files are needed. Apps can either be in `/src/apps` or `/src/customapps`. `/src/customapps` are excluded from git, but `/src/apps` is not., they are both loaded the same way, but a custom app cannot take the same id as a built in app. All apps are loaded as a python module, so your init script should be in `/src/apps/<id>/__init__.py`. The app needs to expose an `app` variable, of the `App` class. This is a basic example of an app that has a few settings.
```python
from flask import render_template, redirect
from init import App, StringSetting, FloatSetting, IntegerSetting, BooleanSetting

app = App("Test App", [
    StringSetting("string-test", "Test string", "Test one\nType whatever you want", "Hello!"),
    StringSetting("hidden-string-test", "", "", "default", True),
    FloatSetting("float-test", "Test float", "Test two\nType a float", 3.14),
    IntegerSetting("integer-test", "Test integer", "Test three\nType an integer", 42),
    BooleanSetting("boolean-test", "Test boolean", "Test four\nToggle this", False)
])

@app.blueprint.route("/settings")  # Results in /apps/<app.id>/settings, which becomes /apps/demoapp/settings for this app
def test_settings():
    return render_template(f"{app.dirname}/pages/settings.html")

@app.blueprint.route("/launch")
def launch(): # Removing or commenting this route results in the app not showing on the dashboard
    return redirect(f"/apps/{app.dirname}/settings")
```
If you use this code, you should have a `/apps/<id>/pages/settings.html` with some basic content, following this loose structure:
```html
{% extends "templates/app.html" %}
{% block head %}
<!-- Any styles, or really anything that should go in <head> should go here -->
<style>
    html, body {
        overflow: hidden;
    }
</style>
{% endblock %}
{% block content %}
<!-- Anything visible goes here -->
<h1 id="auto-time"></h1> <!-- This is automatically filled in with the current time by the app, no javascript needed. -->
<span id="appid">This is the {{app.id}} app!</span>
{% endblock %}
{% block script %}
<!-- Any scripts should go here -->
<script>
    alert("hi!")
</script>
{% endblock %}
```
To make more complex apps, look around at the built in apps to see what you can do! While there are no docs yet, PYThing is made to be easy to extend, and part of the experience is making your own app!

</details>

<details>
   <summary>
      <h2>🏗️ Building</h2>
   </summary>

Building pything with your modifications can be done by either running `build.sh` (linux, from within your virtual environment) or `build.bat` (windows). The result should be in `dist`. Keep in mind that apps must be in `/src/apps` to be included in the build.
</details>