from flask import render_template, request, redirect
from init import App, get_apps, BooleanSetting
import webbrowser

app = App([BooleanSetting("warn", "Show settings hint (turn me off)", True)])


@app.on_setting_update
def hidewarn(changed: dict[str, object]):
    if "warn" in changed:
        app.settings["warn"].hidden = not changed["warn"]


hidewarn({})


@app.blueprint.route("/launch")
def launch():
    return render_template(f"{app.dirname}/pages/index.html", apps=get_apps())

@app.blueprint.route("/settings")
def opensettings():
    webbrowser.open_new("http://127.0.0.1:5192/settings")
    return redirect("/apps/dashboard/launch")