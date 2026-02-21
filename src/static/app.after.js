const autoTime = document.getElementById("auto-time")
if (autoTime) {
    console.log("Found auto-time element")
    setInterval(() => {
        updateAutoTime(autoTime)
    }, 1000);
}