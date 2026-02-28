# PYThing

PYThing is a python version of [DeskThing](https://github.com/ItsRiprod/DeskThing), designed to be easy to write apps for, and to be light on the client. The client just needs chrome and access to the host port in any way, and does not need internet (the host does).

## Features

- Automatic carthing connection
- Easy setup
- Light on the client
- Very extendable

## Usage

Clone this repo

Install dependencies with `pip install -r requirements.txt`, on linux you may need to make a virtual environment first

Run `python3 src/init.py`

Configure to your liking at http://127.0.0.1:5192/settings

### With a Car Thing

The Car Thing should be automatically detected when plugged in to your computer. The device will be returned to it's previous state on restart. You can close the current app with the upper right button.

### Without a Car Thing

You won't get the full experience, but you may access the client view from http://127.0.0.1:5192 and all apps should work fine. You can navigate the dashboard with mouse or arrow keys and enter, and close apps with m.

## Troubleshooting

### My Car Thing won't connect

Make sure you are running the custom Thing Labs firmware, if the device is not detected by the script, make sure the device shows up in ADB. You may need udev rules on linux.

## Apps

All apps can store data in the form of settings, you can access any visible settings from `/settings`

- Clock
    - A basic clock app
    - Use it as a template for a static application
- System
    - Shows information about your computer
        - RAM
        - CPU
        - Disk
        - Network
    - Use it as a template for a display app
- Music
    - Provider that can take input from other apps.
    - Basically, takes input from a 'provider' app, and passes that data to everything else.
    - Injects code into the client to display the provided information (playbar)
- Spotify
    - A music provider app,
- Lyrics
    - An app that takes the data from the music provider, and gets the lyrics for the current song.

### Make your own

Apps have a defined structure, but not all files are needed. Apps can either be in `/apps` or `/customapps`. `/customapps` are excluded from git, but `/apps` is not., they are both loaded the same way, but a custom app cannot take the same id as a built in app. All apps are loaded as a python module, so your init script should be in `/apps/<id>/__init__.py`. The app needs to expose an `app` variable, of the `App` class. This is a basic example of an app that has a few settings.
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
<h1 id="auto-time"></h1> <!-- This is automatically filled in with the current time, no javascript needed. -->
<span id="appid">This is the {{app.id}} app!</span>
{% endblock %}
{% block script %}
<!-- Any scripts should go here -->
<script>
    alert("hi!")
</script>
{% endblock %}
```
To make more complex apps, look around at the built in app to see what you can do! Even better, try removing some built in apps (Just delete the folder, no config needed) and see what stops working.