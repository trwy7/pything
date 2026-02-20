const socket = io();
const appFrame = document.getElementById("appframe")
var accent = "hsl(165, 46%, 68%)";
function triggerLoadAnim(keep=false) {
    document.getElementById("loadanim").classList.add("reload")
    if (!keep) {
        setTimeout(() => {
            document.getElementById("loadanim").classList.remove("reload")
        }, 600)
    }
}
function sendToApp(command, data) {
    appFrame.contentWindow.postMessage({cmd: command, data: data}, '*');
}
window.addEventListener('message', (event) => {
    const rmsg = event.data
    switch (rmsg.cmd) {
        case "openApp":
            socket.emit("open_app", rmsg.data)
            console.log("Switching to " + rmsg.data)
            break;
        default:
            console.error("Unknown command recieved: " + rmsg.cmd);
            alert("Unknown command recieved: " + rmsg.cmd);
    }
})
socket.on("connect", () => {
    console.log("Connected to server");
});
socket.on("disconnect", () => {
    socket.disconnect();
    window.focus();
    document.getElementById("status").innerText = "Disconnected";
    document.getElementById("status").style.backgroundColor = "red";
    document.getElementById("status").style.display = "block";
    x = setInterval(
        function() {
            fetch("http://localhost:5192/isready", { method: 'GET' })
            .then(response => {
            if (response.ok) {
                triggerLoadAnim(keep=true)
                setTimeout(() => {
                    window.location.reload();
                }, 500)
                clearInterval(x);
            }
            })
            .catch(error => {});
        },
        1000
    );
});
socket.on("changeframe", (frame) => {
    triggerLoadAnim();
    window.focus();
    setTimeout(() => {document.getElementById("appframe").src = frame;}, 500);
    setTimeout(() => {appFrame.contentWindow.focus();}, 1100);
})
socket.on("accentcolor", (color) => {
    // TODO: Make apps able to set this color (or base it on the current song)
    // FIXME: not actually a fixme but a reminder to make sure this is always a bright color
    document.body.style.setProperty('--background-color', color);
    accent = color
})
let ctime = null
let offset = 0
socket.on("dt", (ttime) => {
    ctime = new Date(ttime)
    offset = ctime - new Date()
    sendToApp("offset", offset);
})
setTimeout(() => {appFrame.contentWindow.focus();}, 500)