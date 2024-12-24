const anyBtn = document.getElementById("anyBtn");
const startBtn = document.getElementById("startBtn");
const stopBtn = document.getElementById("stopBtn");
const progressBar = document.getElementById("progressBar");
const statusLog = document.getElementById("statusLog");

const options = { mimeType: "audio/webm; codecs=opus" };
let ws;
let stream;
let mediaRecorder;
let recordingDuration = 10; // seconds
let recordingTimer;

let source;
let microphoneStream;

const constraints = {
    audio: {
        sampleSize: 16,
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: false,
        autoGainControl: false,
    },
};

let audioBuffer = []; // Queue to store audio chunks

let sourceNode,
    audioQueue = [],
    isPlaying = false;
let sampleRate = 24000;
let gainNode;
let audioContext;

function convertPCMToFloat32(buffer) {
    const int16Array = new Int16Array(buffer);
    const float32Array = new Float32Array(int16Array.length);
    for (let i = 0; i < int16Array.length; i++) {
        float32Array[i] = int16Array[i] / 32768; // Normalize to [-1.0, 1.0]
    }
    return float32Array;
}

async function playAudio() {
    if (isPlaying || audioQueue.length === 0) return;

    isPlaying = true;

    while (audioContext && audioQueue.length > 0) {
        // Create a source to play the buffer from queue
        const source = audioContext.createBufferSource();
        source.buffer = audioQueue.shift();

        // Connect the source to the audio context destination
        source.connect(audioContext.destination);

        // Play the buffer and wait for it to finish
        const playPromise = new Promise((resolve) => {
            source.onended = resolve;
            source.start();
        });

        try {
            await playPromise; // Wait for the current buffer to finish playing
        } catch (err) {
            console.error("Error during playback:", err);
        }
    }

    isPlaying = false; // Mark as not playing once the queue is empty
    logStatus("<em>stop speeking, " + audioQueue.length + "</em>", "center");
}

function logStatus(msg, where) {
    const dt = new Date();
    const dt_str = dt.toLocaleTimeString("en-US", {
        hour12: false,
    });
    const ms_str = "";
    ("000" + dt.getMilliseconds()).slice(-3);
    where = where || "start";
    tm = `<div class="time">${dt_str}${ms_str}</div>`;
    statusLog.innerHTML += `<div class='my-2 text-${where}'>${tm}${msg}</div>`;
    statusLog.parentElement.scrollTop = 10000000;
}

anyBtn.addEventListener("click", async () => {
    // gainNode.gain.value = 0.3;

    if (ws && ws.readyState === ws.OPEN) {
        ws.send(JSON.stringify({ command: "do_something" }));
        anyBtn.disabled = true;
        setTimeout(() => {
            anyBtn.disabled = false;
        }, 1000);
    }
});

startBtn.addEventListener("click", async () => {
    startBtn.disabled = true;
    stopBtn.disabled = false;

    // Initialize audio context
    audioContext = new (window.AudioContext || window.webkitAudioContext)();
    gainNode = audioContext.createGain();

    ws = new WebSocket("ws://localhost:8080/ws");

    ws.binaryType = "arraybuffer";

    ws.onopen = async () => {
        microphoneStream =
            await navigator.mediaDevices.getUserMedia(constraints);

        source = audioContext.createMediaStreamSource(microphoneStream);
        source.connect(gainNode);

        logStatus("<em>microphone acquired</em>", "center");

        mediaRecorder = new MediaRecorder(microphoneStream, options);
        // gainNode.gain.value = 0.2;

        mediaRecorder.ondataavailable = (e) => {
            if (e.data.size > 0 && ws.readyState === ws.OPEN) {
                ws.send(e.data);
            }
        };

        mediaRecorder.start(250); // Send chunks every N ms

        ws.send(JSON.stringify({ command: "start_recording" }));
        anyBtn.disabled = false;
    };

    ws.onmessage = async (event) => {
        if (event.data instanceof ArrayBuffer) {
            // Convert raw PCM to Float32
            const floatData = convertPCMToFloat32(event.data);

            const samples = floatData.length;

            // Create an AudioBuffer
            const buffer = audioContext.createBuffer(1, samples, sampleRate);
            buffer.getChannelData(0).set(floatData);

            // Queue and play the buffer
            audioQueue.push(buffer);

            if (!isPlaying) await playAudio();

            ///
        } else if (typeof event.data === "string") {
            let data;
            try {
                data = JSON.parse(event.data);
            } catch (err) {
                logStatus(
                    "<em>Received non-JSON text: " + event.data + "</em>",
                );
                return;
            }

            if (data.status) {
                logStatus(
                    "<em class='text-black-50'>" + data.status + "</em>",
                    "center",
                );
            }
            if (data.response) {
                logStatus(
                    "<em class='text-black'>" + data.response + "</em>",
                    "end",
                );
            }
            if (data.request) {
                logStatus("<em class='text-primary'>" + data.request + "</em>");
            }
            if (data.abort) {
                logStatus("<em class='text-danger'>ABORT</em>");
            }
        }
    };

    ws.onclose = () => {
        logStatus("<em>WebSocket closed.</em>");

        if (mediaRecorder && mediaRecorder.state !== "inactive") {
            mediaRecorder.stop();
        }
        microphoneStream.getTracks().forEach((track) => track.stop());

        startBtn.disabled = false;
        stopBtn.disabled = true;
        anyBtn.disabled = true;
    };

    ws.onerror = (err) => {
        logStatus("<em>WebSocket error: " + err + "</em>", "center");
    };
});

stopBtn.addEventListener("click", () => {
    clearInterval(recordingTimer);
    if (mediaRecorder && mediaRecorder.state !== "inactive") {
        mediaRecorder.stop();
    }
    microphoneStream.getTracks().forEach((track) => track.stop());

    ws.send(JSON.stringify({ command: "stop_recording" }));

    startBtn.disabled = false;
    stopBtn.disabled = true;
    anyBtn.disabled = true;
});
