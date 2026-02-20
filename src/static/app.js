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
// Exposed functions
function openApp(app) {
    sendToClient("openApp", app)
}