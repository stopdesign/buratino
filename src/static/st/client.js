// DOM Elements
const dataChannelLog = document.getElementById("data-channel");

const iceConnectionLog = document.getElementById("ice-connection-state");
const iceGatheringLog = document.getElementById("ice-gathering-state");
const signalingLog = document.getElementById("signaling-state");

const statusElement = document.getElementById("status");
const audio = document.getElementById("audio");

const canvas = document.getElementById("spectre");
const canvasCtx = canvas.getContext("2d");

audio.volume = 1.0;

let pc = null,
    reconnect = null,
    dc = null,
    dcInterval = null;

// Add a visualizer for audio
const visualizeAudio = (stream) => {
    const audioContext = new window.AudioContext();
    const analyser = audioContext.createAnalyser();
    const source = audioContext.createMediaStreamSource(stream);

    // Connect the audio stream to the analyser
    source.connect(analyser);

    analyser.fftSize = 256;
    const bufferLength = analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);

    const draw = () => {
        canvasCtx.clearRect(0, 0, canvas.width, canvas.height);

        // Get frequency data
        analyser.getByteFrequencyData(dataArray);

        // Draw frequency bars (spectrogram)
        const barWidth = (canvas.width / bufferLength) * 2.5;
        let x = 0;

        dataArray.forEach((value) => {
            const barHeight = value / 2;
            canvasCtx.fillStyle = `rgb(${value + 100}, 50, 50)`;
            canvasCtx.fillRect(x, canvas.height - barHeight, barWidth, barHeight);
            x += barWidth + 1;
        });

        requestAnimationFrame(draw);
    };

    draw();
};

document.getElementById("stop").disabled = true;
document.getElementById("f1").disabled = true;

// Helper: Get formatted timestamp
const getTimestamp = () => {
    var tzoffset = new Date().getTimezoneOffset() * 60000;
    return new Date(Date.now() - tzoffset).toISOString().slice(11, 19);
};

// Create PeerConnection
const createPeerConnection = () => {
    const iceServers = [
        { urls: "turns:turn.grrr.sh:5349", username: "tester1", credential: "flash1" },
    ];
    const config = {
        sdpSemantics: "unified-plan",
        iceServers: iceServers,
    };

    pc = new RTCPeerConnection(config);

    // Event Listeners
    const addLogListener = (event, element, property) => {
        pc.addEventListener(event, () => (element.textContent += ` -> ${pc[property]}`));
        element.textContent = pc[property];
    };

    addLogListener("icegatheringstatechange", iceGatheringLog, "iceGatheringState");
    addLogListener("iceconnectionstatechange", iceConnectionLog, "iceConnectionState");
    addLogListener("signalingstatechange", signalingLog, "signalingState");

    pc.addEventListener("track", (e) => (audio.srcObject = e.streams[0]));

    pc.onicecandidateerror = (e) => console.error("ICE Candidate Error:", e.errorText);

    // pc.onicecandidate = ({ candidate }) => console.log(candidate?.candidate || candidate);

    pc.addEventListener("connectionstatechange", () => {
        statusElement.innerHTML = pc.connectionState;
        statusElement.className = `status-${pc.connectionState}`;
    });

    return pc;
};

// Populate Input Devices
const enumerateInputDevices = async () => {
    try {
        const devices = await navigator.mediaDevices.enumerateDevices();
        const populateSelect = (select, devices) => {
            devices.forEach(({ deviceId, label }, idx) => {
                const option = new Option(label || `Device #${idx + 1}`, deviceId);
                select.appendChild(option);
            });
        };
        populateSelect(
            document.getElementById("audio-input"),
            devices.filter((d) => d.kind === "audioinput"),
        );
    } catch (error) {
        console.error(error);
    }
};

// Negotiate Connection
const negotiate = async () => {
    try {
        await pc.setLocalDescription(await pc.createOffer());
        await new Promise((resolve) => {
            if (pc.iceGatheringState === "complete") return resolve();
            const checkState = () => {
                if (pc.iceGatheringState === "complete") {
                    pc.removeEventListener("icegatheringstatechange", checkState);
                    resolve();
                }
            };
            pc.addEventListener("icegatheringstatechange", checkState);
        });
        const offer = pc.localDescription;
        const response = await fetch("/offer", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ sdp: offer.sdp, type: offer.type }),
        });
        const answer = await response.json();
        await pc.setRemoteDescription(answer);
    } catch (error) {
        console.error(error);
    }
};

// Media Constraints
const getMediaConstraints = () => ({
    audio: {
        channelCount: 1, // doesn't work for me
        sampleRate: 24000,
        echoCancellation: true,
        noiseSuppression: false,
        autoGainControl: false,
        suppressLocalAudioPlayback: false,
        voiceIsolation: false,
    },
});

// Start Connection
const start = () => {
    reconnect = true;
    connect();
};

const connect = async () => {
    try {
        if (await isHostUp(window.location.href)) _connect();
        else statusElement.innerHTML = "host is down";
    } catch (e) {
        console.error(e);
    }
};

const _connect = async () => {
    document.getElementById("start").disabled = true;
    pc = createPeerConnection();
    dc = pc.createDataChannel("chat", { ordered: true });

    dc.onopen = () => {
        reconnect = true;
        dataChannelLog.innerHTML += `<p><span>${getTimestamp()}</span> <b>open</b></p>`;
        dcInterval = setInterval(() => dc.send(`ping ${Date.now()}`), 5000);
        document.getElementById("f1").disabled = false;
    };

    dc.onclose = () => {
        clearInterval(dcInterval);
        dataChannelLog.innerHTML += `<p><span>${getTimestamp()}</span> <b>close</b></p><hr/>`;
        resetButtons();
        pc.getSenders().forEach(({ track }) => track?.stop());
        dc.close();
        pc.close();

        setTimeout(() => {
            pc.dispatchEvent(new Event("connectionstatechange"));
            pc.dispatchEvent(new Event("signalingstatechange"));
            pc.dispatchEvent(new Event("iceconnectionstatechange"));
        }, 100);
    };

    dc.onmessage = ({ data }) => {
        if (data.startsWith("pong")) return;

        const message = JSON.parse(data);

        const ts = message.ts;
        const role = message.role;
        const content = message.content;

        const offset = new Date().getTimezoneOffset() * 60000;
        const dt = new Date(ts - offset).toISOString().slice(11, 19);

        dataChannelLog.innerHTML += `<p class="role-${role}"><span>${dt}</span> <em>${content}</em></p>`;
        dataChannelLog.parentElement.scrollTop = 100000;

        if (role == "command" && content == "mute") {
            // console.log("CLICK");
            audio.volume = 0.2;
            setTimeout(() => (audio.volume = 1), 1500);
        }
    };

    const constraints = getMediaConstraints();
    const device = document.getElementById("audio-input").value;
    if (device) constraints.audio.deviceId = { exact: device };

    const txt = JSON.stringify(constraints, null, 2);
    dataChannelLog.innerHTML += `<p><span>${getTimestamp()}</span> <pre>${txt}</pre></p>`;

    try {
        const stream = await navigator.mediaDevices.getUserMedia(constraints);
        stream.getTracks().forEach((track) => pc.addTrack(track, stream));

        await negotiate();
        visualizeAudio(stream);
    } catch (error) {
        alert(`Could not acquire media: ${error}`);
    }

    document.getElementById("stop").disabled = false;
};

// Utility Functions
const resetButtons = () => {
    document.getElementById("start").disabled = false;
    document.getElementById("stop").disabled = true;
    document.getElementById("f1").disabled = true;
};

const stop = () => {
    reconnect = false;
    resetButtons();
    pc.close();
    dc.close();
};

const f1 = () => {
    if (dc.readyState == "open") {
        dc.send("save_audio");
    }
};

async function isHostUp(url, timeout = 500) {
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

// Periodic Host Check
setInterval(() => {
    if (reconnect && (!pc || ["failed", "closed"].includes(pc.connectionState))) connect();
}, 3000);

enumerateInputDevices();
