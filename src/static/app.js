const appId = document.querySelector('meta[name="app-id"]').content

// Internal functions
function sendToClient(command, data) {
    window.parent.postMessage({cmd: command, data: data}, '*');
}
window.addEventListener('message', (event) => {
    const rmsg = event.data
    switch (rmsg.cmd) {
        case "offset":
            timeOffset = rmsg.data;
            break;
        default:
            console.error("Unknown command recieved: " + rmsg.cmd);
            alert("Unknown command recieved: " + rmsg.cmd);
    }
})
// Utilities
document.addEventListener('keydown', function(event) {
    event.preventDefault();
    if (event.key === 'm') {
        openApp('dashboard');
    }
});
let timeOffset = 0;
function getRealDate() {
    return new Date(Date.now() + timeOffset)
}
// app-server communication
function send(event, data) {
    sendToClient("appCom", {app: appId, event: event, data: data})
}
// Exposed functions
function openApp(app) {
    sendToClient("openApp", app)
}