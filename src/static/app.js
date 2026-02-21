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
            at = document.getElementById("auto-time");
            if (at) {
                updateAutoTime(at);
            }
            break;
        case "appCom":
            if (rmsg.data.app != appId) {
                console.warn("Server just sent an event to app '" + rmsg.data.app + "' but '" + appId + "' is loaded")
                break;
            }
            func = listeners[rmsg.data.event]
            if (!func) {
                break;
            }
            func(rmsg.data.data)
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
function updateAutoTime(autoTime) {
    const cd = getRealDate()
    var hours = cd.getHours();
    var minutes = cd.getMinutes();
    var ampm = hours >= 12 ? 'PM' : 'AM';
    hours = hours % 12;
    hours = hours ? hours : 12; // the hour '0' should be '12'
    minutes = minutes < 10 ? '0'+minutes : minutes;
    autoTime.innerText = hours + ':' + minutes + ' ' + ampm;
}
// app-server communication
function send(event, data) {
    sendToClient("appCom", {app: appId, event: event, data: data})
}
let listeners = {}
function on(event, func) {
    listeners[event] = func
}
// Exposed functions
function openApp(app) {
    sendToClient("openApp", app)
}