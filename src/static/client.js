const carthing = new URLSearchParams(window.location.search).has("carthing");
const socket = io();
const appFrame = document.getElementById("appframe")
function hideApp() {
    document.getElementById("loadanim").classList.remove("load")
    document.getElementById("loadanim").classList.add("reload")
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
    unhideApp(); // This could make it so the dashboard is loaded early on first reload, but it should be fine.
    setTimeout(() => {
        document.getElementById("loadanim").innerText = ""
    }, 500)
});
socket.on("disconnect", () => {
    socket.disconnect();
    window.focus();
    document.getElementById("status").style.display = "block";
    x = setInterval(
        function() {
            fetch("http://localhost:5192/isready", { method: 'GET' })
            .then(response => {
            if (response.ok) {
                hideApp();
                setTimeout(() => {
                    window.location.reload();
                }, 550)
                clearInterval(x);
            }
            })
            .catch(error => {});
        },
        1000
    );
});
socket.on("changeframe", (frame) => {
    hideApp();
    window.focus();
    setTimeout(() => {document.getElementById("appframe").src = frame;}, 500);
    setTimeout(() => {sendToApp("offset", offset);}, 550);
    setTimeout(() => {sendToApp("offset", offset);}, 600);
    setTimeout(() => {sendToApp("offset", offset);}, 650);
    setTimeout(() => {appFrame.contentWindow.focus();}, 1100);
})
socket.on("app_com", (data) => {
    sendToApp("appCom", {app: data[0], event: data[1], data: data[2]})
})
if (carthing) {
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