import threading
import psutil
import time
import humanize
from flask import render_template
from init import App, BooleanSetting

app = App("System", [
    BooleanSetting("gib", "Values in GiB", "If on, shows data values in GiB instead of GB", False)
])

onet = psutil.net_io_counters()
net_lu = onet.bytes_sent
net_ld = onet.bytes_recv
del onet

@app.blueprint.route("/launch")
def launch():
    return render_template(f"{app.dirname}/pages/hw.html")

def send_stats_thread():
    global net_lu, net_ld
    while True:
        if not app.should_poll():
            time.sleep(1)
            continue
        app.logger.debug("Updating hardware stats")
        ram = psutil.virtual_memory()
        gib = app.settings['gib'].get_value()
        onet = psutil.net_io_counters()
        net_tu = onet.bytes_sent
        net_td = onet.bytes_recv
        payload = {
            'rp': ram.percent,
            'ru': humanize.naturalsize(ram.used, binary=gib),
            'rt': humanize.naturalsize(ram.total, binary=gib),
            'cpu': psutil.cpu_percent(interval=None),
            'netdt': humanize.naturalsize(net_td, binary=gib),
            'netut': humanize.naturalsize(net_tu, binary=gib),
            'netdr': humanize.naturalsize(net_td - net_ld, binary=gib),
            'netur': humanize.naturalsize(net_tu - net_lu, binary=gib)
        }
        net_lu = net_tu
        net_ld = net_td
        app.send("upd", payload)
        time.sleep(1)

threading.Thread(target=send_stats_thread, daemon=True).start()