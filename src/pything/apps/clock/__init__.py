from pything.app import App
from pything.web import render_template

app = App([])


@app.blueprint.route("/launch")
def launch():
    return render_template(f"{app.dirname}/pages/clock.html")
