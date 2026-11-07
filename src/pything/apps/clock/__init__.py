from pything import App, render_template

app = App([])


@app.blueprint.route("/launch")
def launch():
    return render_template(f"{app.dirname}/pages/clock.html")
