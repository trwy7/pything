const isHardware = new URLSearchParams(window.location.search).has("device");
const socket = {
    _handlers: {},
    _ws: null,
    get connected() {
        return this._ws !== null && this._ws.readyState === WebSocket.OPEN;
    },
    listFor(event) {
        if (!(event in this._handlers)) {
            this._handlers[event] = [];
        }
        return this._handlers[event];
    },
    on(event, cb) {
        this.listFor(event).push(cb);
    },
    emit(event, ...args) {
        if (this.connected) {
            this._ws.send(JSON.stringify({event: event, args: args}));
        }
    },
    _dispatch(event, args) {
        (this._handlers[event] || []).forEach((cb) => {
            cb(...args);
        });
    },
    _connect() {
        const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
        const ws = new WebSocket(`${proto}//${window.location.host}/ws`);
        ws.onopen = () => {
            socket._ws = ws;
            socket._dispatch("connect", []);
        };
        ws.onmessage = (e) => {
            try {
                const msg = JSON.parse(e.data);
                socket._dispatch(msg.event, msg.args || []);
            } catch (err) {
                console.warn("Ignoring invalid websocket message", e.data);
            }
        };
        ws.onerror = () => {
            try { ws.close(); } catch (err) {}
        };
        ws.onclose = () => {
            socket._ws = null;
            socket._dispatch("disconnect", []);
        };
    },
};
socket._connect();

const appFrame = document.getElementById("appframe")
function hideApp(msg="") {
    document.getElementById("loadanim").classList.remove("load")
    document.getElementById("loadanim").classList.add("reload")
    document.getElementById("loadanim").innerText = msg
}
function unhideApp() {
    if (!socket.connected) {
        return;
    }
    document.getElementById("loadanim").classList.remove("reload")
    document.getElementById("loadanim").classList.add("load")
}
function sendToApp(command, data) {
    appFrame.contentWindow.postMessage({cmd: command, data: data}, '*');
}
let alf = [] // app load functions
function onAppLoad(func) {
    alf.push(func)
}
onAppLoad(() => {sendToApp("offset", offset); appFrame.contentWindow.focus();})
window.addEventListener('message', (event) => {
    const rmsg = event.data
    switch (rmsg.cmd) {
        case "openApp":
            socket.emit("open_app", rmsg.data)
            console.log("Switching to " + rmsg.data)
            break;
        case "appCom":
            socket.emit("app_com", rmsg.data.app, rmsg.data.event, rmsg.data.data)
            break;
        case "loaded":
            alf.forEach((naf) => {
                naf()
            })
            console.log("App has loaded");
            unhideApp();
            break;
    }
})
socket.on("connect", () => {
    console.log("Connected to server");
    document.getElementById("appframe").src = "/apps/dashboard/launch";
});
var reloadinterval = null
socket.on("disconnect", () => {
    window.focus();
    document.getElementById("status").style.display = "block";
    hideApp("Disconnected")
    if (reloadinterval) {
        return;
    }
    reloadinterval = setInterval(
        function() {
            fetch("http://localhost:5192/isready", { method: 'GET' })
            .then(response => {
            if (response.ok) {
                hideApp();
                setTimeout(() => {
                    window.location.reload();
                }, 550)
                clearInterval(reloadinterval);
            }
            })
            .catch(error => {});
        },
        1000
    );
});
var appChangeListeners = []
function onAppChange(func) {
    appChangeListeners.push(func)
}
socket.on("changeframe", (frame) => {
    hideApp();
    window.focus();
    const fsplit = frame.split("/")
    if (fsplit.length >= 3) {
        currentApp = fsplit[2];
    } else {
        currentApp = null;
    }
    setTimeout(() => {
        document.getElementById("appframe").src = frame;
        appChangeListeners.forEach((listener) => {
            listener(currentApp); // notify listeners before changing the frame
        });
    }, 500);

})
socket.on("shutdown", () => {
    hideApp("Stopping...")
})
socket.on("app_com", (data) => {
    sendToApp("appCom", {app: data[0], event: data[1], data: data[2]})
})
if (isHardware) {
    document.body.classList.add("round")
}
let ctime = null
let offset = 0
socket.on("dt", (ttime) => {
    ctime = new Date(ttime)
    offset = ctime - new Date()
    sendToApp("offset", offset);
})
appFrame.contentWindow.focus();
