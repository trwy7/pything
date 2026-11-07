import webbrowser

from pything import App, BooleanSetting, get_apps, redirect, render_template

app = App([BooleanSetting("warn", "Show settings hint (turn me off)", True)])


@app.on_setting_update
def hidewarn(changed: dict[str, object]):
    if "warn" in changed:
        app.settings["warn"].hidden = not changed["warn"]


hidewarn({"warn": app.settings["warn"].get_value()})


@app.blueprint.route("/launch")
def launch():
    return render_template(f"{app.dirname}/pages/index.html", apps=get_apps())


@app.blueprint.route("/settings")
def opensettings():
    webbrowser.open_new("http://127.0.0.1:5192/settings")
    return redirect("/apps/dashboard/launch")
