import threading
import psutil
import time
from flask import render_template
from init import App, BooleanSetting

app = App("System", [
    BooleanSetting("ram-gib", "Ram in GiB", "If on, shows ram in GiB instead of GB", False)
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
        rmult = 1073741824 if app.settings['ram-gib'].get_value() else 1e9
        payload = {
            'rp': ram.percent,
            'ru': round(ram.used / rmult, 2),
            'rt': round(ram.total / rmult, 2),
            'rl': "GiB" if rmult == 1073741824 else "GB"
        }
        app.send("upd", payload)
        time.sleep(1)

threading.Thread(target=send_stats_thread, daemon=True).start()