// get DOM elements
var dataChannelLog = document.getElementById("data-channel"),
    iceConnectionLog = document.getElementById("ice-connection-state"),
    iceGatheringLog = document.getElementById("ice-gathering-state"),
    signalingLog = document.getElementById("signaling-state"),
    statusElement = document.getElementById("status");

var audio = document.getElementById("audio");
audio.volume = 1;

// peer connection
var pc = null;

var reconnect = null;

// data channel
var dc = null,
    dcInterval = null;

document.getElementById("stop").disabled = true;

function createPeerConnection() {
    var config = {
        sdpSemantics: "unified-plan",
        iceServers: [
            {
                urls: "turns:turn.grrr.sh:5349",
                username: "tester1",
                credential: "flash1",
            },
        ],
    };

    pc = new RTCPeerConnection(config);

    // register some listeners to help debugging
    pc.addEventListener(
        "icegatheringstatechange",
        () => {
            iceGatheringLog.textContent += " -> " + pc.iceGatheringState;
        },
        false,
    );
    iceGatheringLog.textContent = pc.iceGatheringState;

    pc.addEventListener(
        "iceconnectionstatechange",
        () => {
            iceConnectionLog.textContent += " -> " + pc.iceConnectionState;
        },
        false,
    );
    iceConnectionLog.textContent = pc.iceConnectionState;

    pc.addEventListener(
        "signalingstatechange",
        () => {
            signalingLog.textContent += " -> " + pc.signalingState;
        },
        false,
    );
    signalingLog.textContent = pc.signalingState;

    // connect audio
    pc.addEventListener("track", (evt) => {
        audio.srcObject = evt.streams[0];
    });

    pc.onicecandidateerror = (event) => {
        console.error("ICE Candidate Error:", event.errorText);
    };

    pc.onicecandidate = (event) => {
        if (event.candidate) {
            if (event.candidate.candidate) {
                console.log(event.candidate.candidate);
            } else {
                console.log(event.candidate);
            }
        }
    };

    pc.addEventListener(
        "connectionstatechange",
        () => {
            statusElement.innerHTML = pc.connectionState;
            switch (pc.connectionState) {
                case "new":
                case "connecting":
                    console.info("Connecting…");
                    break;
                case "connected":
                    console.info("Online");
                    break;
                case "disconnected":
                    console.info("Disconnecting…");
                    break;
                case "closed":
                    console.info("Offline");
                    break;
                case "failed":
                    console.info("Error");
                    break;
                default:
                    console.info("Unknown");
                    break;
            }
        },
        false,
    );

    return pc;
}

function enumerateInputDevices() {
    const populateSelect = (select, devices) => {
        let counter = 1;
        devices.forEach((device) => {
            const option = document.createElement("option");
            option.value = device.deviceId;
            option.text = device.label || "Device #" + counter;
            select.appendChild(option);
            counter += 1;
        });
    };

    navigator.mediaDevices
        .enumerateDevices()
        .then((devices) => {
            populateSelect(
                document.getElementById("audio-input"),
                devices.filter((device) => device.kind == "audioinput"),
            );
        })
        .catch((e) => {
            console.error(e);
        });
}

function negotiate() {
    return pc
        .createOffer()
        .then((offer) => {
            return pc.setLocalDescription(offer);
        })
        .then((a) => {
            // wait for ICE gathering to complete
            return new Promise((resolve) => {
                if (pc.iceGatheringState === "complete") {
                    resolve();
                } else {
                    function checkState() {
                        if (pc.iceGatheringState === "complete") {
                            pc.removeEventListener(
                                "icegatheringstatechange",
                                checkState,
                            );
                            resolve();
                        }
                    }
                    pc.addEventListener("icegatheringstatechange", checkState);
                }
            });
        })
        .then(() => {
            var offer = pc.localDescription;
            var codec;

            codec = document.getElementById("audio-codec").value;
            if (codec !== "default") {
                offer.sdp = sdpFilterCodec("audio", codec, offer.sdp);
            }

            document.getElementById("offer-sdp").textContent = offer.sdp;
            return fetch("/offer", {
                body: JSON.stringify({
                    sdp: offer.sdp,
                    type: offer.type,
                }),
                headers: {
                    "Content-Type": "application/json",
                },
                method: "POST",
            });
        })
        .then((response) => {
            return response.json();
        })
        .then((answer) => {
            document.getElementById("answer-sdp").textContent = answer.sdp;
            return pc.setRemoteDescription(answer);
        })
        .catch((e) => {
            console.error(e);
        });
}

function get_dt() {
    var tzoffset = new Date().getTimezoneOffset() * 60000;
    var dt = new Date(Date.now() - tzoffset).toISOString().slice(11, 23);
    return dt;
}

function start() {
    reconnect = true;
    connect();
}

function connect() {
    (async () => {
        const isUp = await isHostUp(window.location.href);
        console.log("host is up?", isUp);
        if (isUp) {
            _connect();
        } else {
            statusElement.innerHTML = "host is down";
        }
    })();
}

function _connect() {
    document.getElementById("start").disabled = true;

    pc = createPeerConnection();

    var time_start = null;

    const current_stamp = () => {
        if (time_start === null) {
            time_start = new Date().getTime();
            return 0;
        } else {
            return new Date().getTime() - time_start;
        }
    };

    var parameters = JSON.parse(
        document.getElementById("datachannel-parameters").value,
    );

    dc = pc.createDataChannel("chat", parameters);
    dc.addEventListener("close", () => {
        clearInterval(dcInterval);
        dataChannelLog.textContent += `${get_dt()} close\n`;

        reset_btns();

        // close local audio
        pc.getSenders().forEach((sender) => {
            if (sender.track) {
                sender.track.stop();
            }
        });

        dc.close();
        pc.close();

        setTimeout(() => {
            pc.dispatchEvent(new Event("connectionstatechange"));
            pc.dispatchEvent(new Event("signalingstatechange"));
            pc.dispatchEvent(new Event("iceconnectionstatechange"));
        }, 100);
    });
    dc.addEventListener("open", () => {
        reconnect = true;
        dataChannelLog.textContent += `${get_dt()} open\n`;
        dcInterval = setInterval(() => {
            if (dc && dc.readyState == "open") {
                var message = "ping " + current_stamp();
                dc.send(message);
            }
        }, 5000);
    });

    //////////////////////////////////////
    // DATA CHANNEL MESSAGE
    // ///////////////////////////////////
    dc.addEventListener("message", (evt) => {
        if (evt.data.substring(0, 4) === "pong") {
            // var elapsed_ms = current_stamp() - parseInt(evt.data.substring(5), 10);
            // dataChannelLog.textContent += "ping " + elapsed_ms + " ms\n";
        } else {
            dataChannelLog.textContent += `${get_dt()} << ${evt.data}\n`;

            if (evt.date == "abort") {
                console.log("start fadeOut");
                window.fadeOut();
                setTimeout(() => (audio.volume = 1), 1000);
            }
        }
        dataChannelLog.scrollTop = 10000000;
    });

    // Build media constraints.

    const constraints = {
        audio: {
            // sampleSize: 16,
            // channelCount: 2,
            // sampleRate: 48000,
            echoCancellation: true,
            noiseSuppression: false,
            autoGainControl: false,
            suppressLocalAudioPlayback: false,
            voiceIsolation: false,
            volume: 1.0,
        },
    };

    const audioConstraints = {};

    const device = document.getElementById("audio-input").value;
    if (device) {
        audioConstraints.deviceId = { exact: device };
    }

    console.log("CONSTRAINTS", constraints);

    // Acquire media and start negotiation.
    navigator.mediaDevices.getUserMedia(constraints).then(
        (stream) => {
            stream.getTracks().forEach((track) => {
                pc.addTrack(track, stream);
            });
            console.info("NEGOTIATE");
            return negotiate();
        },
        (err) => {
            alert("Could not acquire media: " + err);
        },
    );

    document.getElementById("stop").disabled = false;
}

function reset_btns() {
    document.getElementById("start").disabled = false;
    document.getElementById("stop").disabled = true;
}

function stop() {
    reconnect = false;

    // close data channel
    if (dc && dc.readyState == "open") {
        reset_btns();

        // close transceivers
        if (pc.getTransceivers) {
            pc.getTransceivers().forEach((transceiver) => {
                if (transceiver.stop) {
                    transceiver.stop();
                }
            });
        }

        // close local audio
        pc.getSenders().forEach((sender) => {
            if (sender.track) {
                sender.track.stop();
            }
        });

        dc.close();

        // close peer connection
        setTimeout(() => {
            pc.close();
        }, 200);
    }
}

setInterval(() => {
    console.log("check host connection");
    if (reconnect !== true) return;
    if (
        !pc ||
        (pc &&
            (pc.connectionState == "failed" ||
                pc.connectionState == "closed" ||
                pc.connectionState == "new"))
    ) {
        console.log("reconnect...");
        try {
            connect();
        } catch (error) {
            console.error(error);
        }
    }
}, 3000);

function f1() {
    if (dc && dc.readyState == "open") {
        dataChannelLog.textContent += `${get_dt()} f1: save audio\n`;
        dc.send("save_audio");
    }
}
function f2() {
    if (dc && dc.readyState == "open") {
        dataChannelLog.textContent += `${get_dt()} f2: time test\n`;
        dc.send("time_test");
    }
}
function f3() {
    if (dc && dc.readyState == "open") {
        dataChannelLog.textContent += `${get_dt()} f3: custom\n`;
        dc.send("f3");
    }
}

// Function to fade out the audio volume
window.fadeOut = function fadeOut(duration = 0.8) {
    const steps = 10;
    const interval = duration / steps;

    let currentVolume = 1;

    const fadeInterval = setInterval(() => {
        if (currentVolume > 0) {
            currentVolume -= 0.9 / steps;
            audio.volume = Math.max(currentVolume, 0);
        } else {
            clearInterval(fadeInterval);
            console.log("fadeOut DONE");
        }
    }, interval * 1000);
};

function f4() {
    dataChannelLog.textContent += `${get_dt()} f4: custom\n`;
    dc.send("f4");

    window.fadeOut();
}

function sdpFilterCodec(kind, codec, realSdp) {
    var allowed = [];
    var rtxRegex = new RegExp("a=fmtp:(\\d+) apt=(\\d+)\r$");
    var codecRegex = new RegExp("a=rtpmap:([0-9]+) " + escapeRegExp(codec));

    var lines = realSdp.split("\n");

    var isKind = false;
    for (var i = 0; i < lines.length; i++) {
        if (lines[i].startsWith("m=" + kind + " ")) {
            isKind = true;
        } else if (lines[i].startsWith("m=")) {
            isKind = false;
        }

        if (isKind) {
            var match = lines[i].match(codecRegex);
            if (match) {
                allowed.push(parseInt(match[1]));
            }

            match = lines[i].match(rtxRegex);
            if (match && allowed.includes(parseInt(match[2]))) {
                allowed.push(parseInt(match[1]));
            }
        }
    }

    var skipRegex = "a=(fmtp|rtcp-fb|rtpmap):([0-9]+)";
    var sdp = "";

    isKind = false;
    for (var i = 0; i < lines.length; i++) {
        if (lines[i].startsWith("m=" + kind + " ")) {
            isKind = true;
        } else if (lines[i].startsWith("m=")) {
            isKind = false;
        }

        if (isKind) {
            var skipMatch = lines[i].match(skipRegex);
            if (skipMatch && !allowed.includes(parseInt(skipMatch[2]))) {
                continue;
            } else {
                sdp += lines[i] + "\n";
            }
        } else {
            sdp += lines[i] + "\n";
        }
    }

    return sdp;
}

function escapeRegExp(string) {
    return string.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); // $& means the whole matched string
}

async function isHostUp(url, timeout = 300) {
    const controller = new AbortController();
    const signal = controller.signal;

    // Set a timeout to abort the fetch request
    const timeoutId = setTimeout(() => controller.abort(), timeout);

    try {
        const response = await fetch(url, { method: "HEAD", signal });
        clearTimeout(timeoutId); // Clear the timeout if the request succeeds
        return response.ok; // Returns true if the response is OK (status 200-299)
    } catch (error) {
        if (error.name === "AbortError") {
            console.error("Request timed out");
        }
        return false;
    }
}

enumerateInputDevices();
