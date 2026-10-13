from flask import render_template
from init import App, get_apps, BooleanSetting

app = App("Dashboard", [
    BooleanSetting('warn', "Show settings hint", True)
], category="core")

@app.on_setting_update
def hidewarn():
    app.settings["warn"].hidden = not app.settings["warn"].get_value()

hidewarn()

@app.blueprint.route("/launch")
def launch():
    return render_template(f"{app.dirname}/pages/index.html", apps=get_apps())