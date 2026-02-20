const autoTime = document.getElementById("auto-time")
if (autoTime) {
    console.log("Found auto-time element")
    setInterval(() => {
        const cd = getRealDate()
        var hours = cd.getHours();
        var minutes = cd.getMinutes();
        var ampm = hours >= 12 ? 'PM' : 'AM';
        hours = hours % 12;
        hours = hours ? hours : 12; // the hour '0' should be '12'
        minutes = minutes < 10 ? '0'+minutes : minutes;
        autoTime.innerText = hours + ':' + minutes + ' ' + ampm;
    }, 1000)
}