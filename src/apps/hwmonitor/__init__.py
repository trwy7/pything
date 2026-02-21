import threading
import psutil
import time
import humanize
from flask import render_template
from init import App, BooleanSetting

app = App("System", [
    BooleanSetting("gib", "Values in GiB", "If on, shows data values in GiB instead of GB", False)
])

@app.blueprint.route("/launch")
def launch():
    return render_template(f"{app.dirname}/pages/hw.html")

def send_stats_thread():
    while True:
        if not app.should_poll():
            time.sleep(1)
            continue
        app.logger.debug("Updating hardware stats")
        ram = psutil.virtual_memory()
        gib = app.settings['gib'].get_value()
        payload = {
            'rp': ram.percent,
            'ru': humanize.naturalsize(ram.used, binary=gib),
            'rt': humanize.naturalsize(ram.total, binary=gib),
            'cpu': psutil.cpu_percent(interval=None)
        }
        app.send("upd", payload)
        time.sleep(1)

threading.Thread(target=send_stats_thread, daemon=True).start()