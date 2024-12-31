// get DOM elements
var dataChannelLog = document.getElementById("data-channel"),
    iceConnectionLog = document.getElementById("ice-connection-state"),
    iceGatheringLog = document.getElementById("ice-gathering-state"),
    signalingLog = document.getElementById("signaling-state");

// peer connection
var pc = null;

// data channel
var dc = null,
    dcInterval = null;

document.getElementById("msg").disabled = true;
document.getElementById("stop").disabled = true;

function createPeerConnection() {
    var config = {
        sdpSemantics: "unified-plan",
        iceServers: [{ urls: "stun:127.0.0.1:3478" }],
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
        document.getElementById("audio").srcObject = evt.streams[0];
    });

    pc.addEventListener(
        "connectionstatechange",
        () => {
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
            alert(e);
        });
}

function negotiate() {
    return pc
        .createOffer()
        .then((offer) => {
            return pc.setLocalDescription(offer);
        })
        .then(() => {
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
            alert(e);
        });
}

function start() {
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

    if (document.getElementById("use-datachannel").checked) {
        var parameters = JSON.parse(
            document.getElementById("datachannel-parameters").value,
        );

        dc = pc.createDataChannel("chat", parameters);
        dc.addEventListener("close", () => {
            clearInterval(dcInterval);
            dataChannelLog.textContent += "- close\n";

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
            dataChannelLog.textContent += "- open\n";
            dcInterval = setInterval(() => {
                if (dc && dc.readyState == "open") {
                    var message = "ping " + current_stamp();
                    dc.send(message);
                }
            }, 3000);
        });
        dc.addEventListener("message", (evt) => {
            if (evt.data.substring(0, 4) === "pong") {
                var elapsed_ms =
                    current_stamp() - parseInt(evt.data.substring(5), 10);
                dataChannelLog.textContent += "ping " + elapsed_ms + " ms\n";
            } else {
                dataChannelLog.textContent += "< " + evt.data + "\n";
            }
            dataChannelLog.scrollTop = 10000000;
        });
    }

    // Build media constraints.

    const constraints = {
        audio: {
            // sampleSize: 16,
            // channelCount: 2,
            echoCancellation: true,
            noiseSuppression: false,
            autoGainControl: false,
        },
    };

    if (document.getElementById("use-audio").checked) {
        const audioConstraints = {};

        const device = document.getElementById("audio-input").value;
        if (device) {
            audioConstraints.deviceId = { exact: device };
        }

        constraints.audio = Object.keys(audioConstraints).length
            ? audioConstraints
            : true;
    }

    // Acquire media and start negociation.

    if (constraints.audio) {
        navigator.mediaDevices.getUserMedia(constraints).then(
            (stream) => {
                stream.getTracks().forEach((track) => {
                    pc.addTrack(track, stream);
                });
                return negotiate();
            },
            (err) => {
                alert("Could not acquire media: " + err);
            },
        );
    } else {
        negotiate();
    }

    document.getElementById("stop").disabled = false;
    document.getElementById("msg").disabled = false;
}

function reset_btns() {
    document.getElementById("start").disabled = false;
    document.getElementById("stop").disabled = true;
    document.getElementById("msg").disabled = true;
}

function stop() {
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

function msg() {
    if (dc && dc.readyState == "open") {
        dataChannelLog.textContent += "cmd: save_audio\n";
        dc.send("save_audio");
    }
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

enumerateInputDevices();
