from flask import render_template
from init import App

app = App([])


@app.blueprint.route("/launch")
def launch():
    return render_template(f"{app.dirname}/pages/clock.html")
