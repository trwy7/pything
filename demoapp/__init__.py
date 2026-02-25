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
    return render_template(f"{app.dirname}/pages/settings.html", app=app)

@app.blueprint.route("/launch")
def launch(): # Removing or commenting this route results in the app not showing on the dashboard
    return redirect(f"/apps/{app.dirname}/settings")