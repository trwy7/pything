from flask import render_template, redirect
from init import App, StringSetting, FloatSetting, IntegerSetting, BooleanSetting

app = App("Test App", [
    StringSetting("string-test", "Test string", "Test one\nType whatever you want", "Hello!"),
    StringSetting("hidden-string-test", "", "", "default"),
    FloatSetting("float-test", "Test float", "Test two\nType a float", 3.14),
    IntegerSetting("integer-test", "Test integer", "Test three\nType an integer", 42),
    BooleanSetting("boolean-test", "Test boolean", "Test four\nToggle this", False)
])

@app.blueprint.route("/settings")  # Results in /apps/<app.id>/settings, which becomes /apps/test/settings for this app
def test_settings():
    return render_template(f"{app.dirname}/pages/settings.html", app=app)

#@app.blueprint.route("/launch")
#def launch():
#    return redirect(f"/apps/{app.dirname}/settings")

# To show the app on the dashboard, add a /launch route, which will be redirected to when the app is clicked
# If this route does not exist, the app will still show up in settings, but will not show up on the dashboard
