function sendToClient(command, data) {
    window.parent.postMessage({cmd: command, data: data}, '*');
}
window.addEventListener('message', (event) => {
    const rmsg = event.data
    switch (rmsg.cmd) {
        default:
            console.error("Unknown command recieved: " + rmsg.cmd);
            alert("Unknown command recieved: " + rmsg.cmd);
    }
})
function openApp(app) {
    sendToClient("openApp", app)
}
document.addEventListener('keydown', function(event) {
    event.preventDefault();
    if (event.key === 'm') {
        openApp('dashboard');
    }
});