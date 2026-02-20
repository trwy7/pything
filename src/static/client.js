const socket = io();
var accent = "hsl(165, 46%, 68%)";
function triggerLoadAnim(keep=false) {
    document.getElementById("loadanim").classList.add("reload")
    if (!keep) {
        setTimeout(() => {
            document.getElementById("loadanim").classList.remove("reload")
        }, 1000)
    }
}
socket.on("connect", () => {
    console.log("Connected to server");
});
socket.on("disconnect", () => {
    socket.disconnect();
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
                }, 1000)
                clearInterval(x);
            }
            })
            .catch(error => {});
        },
        1000
    );
});
socket.on("changeframe", (frame) => {
    document.getElementById("appframe").src = frame
    document.getElementById("appframe").hidden = false
})
socket.on("accentcolor", (color) => {
    // TODO: Make apps able to set this color (or base it on the current song)
    // FIXME: not actually a fixme but a reminder to make sure this is always a bright color
    document.body.style.setProperty('--background-color', color);
    accent = color
})