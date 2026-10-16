from flask import render_template
from init import App, get_apps, BooleanSetting

app = App(
    "Dashboard", [BooleanSetting("warn", "Show settings hint", True)], category="core"
)


@app.on_setting_update
def hidewarn(changed: dict[str, object]):
    if "warn" in changed:
        app.settings["warn"].hidden = not changed["warn"]


hidewarn({})


@app.blueprint.route("/launch")
def launch():
    return render_template(f"{app.dirname}/pages/index.html", apps=get_apps())
