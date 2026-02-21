import threading
import psutil
import time
from flask import render_template
from init import App

app = App("System", [])

@app.blueprint.route("/launch")
def launch():
    return render_template(f"{app.dirname}/pages/hw.html")

def send_stats_thread():
    pass