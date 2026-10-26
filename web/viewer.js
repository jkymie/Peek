"use strict";

// Página de quem assiste. Protocolo da sinalização: veja host/server.py.

const STUN_SERVERS = ["stun:stun.l.google.com:19302"];
const ICE_GATHERING_TIMEOUT_MS = 3000;

const TEXT = {
  connecting: "Conectando…",
  ended: "A transmissão terminou.",
  full: "Já tem muita gente assistindo. Tente de novo daqui a pouco.",
  failed: "Não foi possível conectar. Tente outro navegador ou outra rede.",
};

const video = document.getElementById("video");
const statusEl = document.getElementById("status");
const unmuteButton = document.getElementById("unmute");

let pc = null;
let finished = false;

function showStatus(text) {
  statusEl.textContent = text;
  statusEl.hidden = !text;
}

function finish(text) {
  if (finished) return;
  finished = true;
  showStatus(text);
  unmuteButton.hidden = true;
  if (pc) pc.close();
  video.srcObject = null;
}

function waitForIceGathering(peer) {
  // O Peek (aiortc) recebe todos os candidatos de uma vez, junto com a oferta.
  if (peer.iceGatheringState === "complete") return Promise.resolve();
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, ICE_GATHERING_TIMEOUT_MS);
    peer.addEventListener("icegatheringstatechange", () => {
      if (peer.iceGatheringState === "complete") {
        clearTimeout(timer);
        resolve();
      }
    });
  });
}

function unmute() {
  video.muted = false;
  video.play().catch(() => {});
  unmuteButton.hidden = true;
}

async function connect() {
  showStatus(TEXT.connecting);
  const wsUrl = `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}${location.pathname.replace(/\/$/, "")}/ws`;
  const ws = new WebSocket(wsUrl);

  pc = new RTCPeerConnection({ iceServers: [{ urls: STUN_SERVERS }] });
  pc.addTransceiver("video", { direction: "recvonly" });
  pc.addTransceiver("audio", { direction: "recvonly" });

  const stream = new MediaStream();
  video.srcObject = stream;
  pc.addEventListener("track", (event) => {
    stream.addTrack(event.track);
    if (event.track.kind === "audio" && video.muted) unmuteButton.hidden = false;
  });

  video.addEventListener("playing", () => showStatus(""), { once: true });

  pc.addEventListener("connectionstatechange", () => {
    if (pc.connectionState === "failed") finish(TEXT.failed);
  });

  ws.addEventListener("message", async (event) => {
    const message = JSON.parse(event.data);
    if (message.type === "answer") {
      await pc.setRemoteDescription({ type: "answer", sdp: message.sdp });
    } else if (message.type === "ended") {
      finish(TEXT.ended);
    } else if (message.type === "full") {
      finish(TEXT.full);
    }
  });

  ws.addEventListener("close", () => {
    // Fechou sem aviso: ou o Peek foi fechado, ou a conexão caiu.
    finish(pc.connectionState === "connected" ? TEXT.ended : TEXT.failed);
  });

  await new Promise((resolve, reject) => {
    ws.addEventListener("open", resolve, { once: true });
    ws.addEventListener("error", reject, { once: true });
  });

  await pc.setLocalDescription(await pc.createOffer());
  await waitForIceGathering(pc);
  ws.send(JSON.stringify({ type: "offer", sdp: pc.localDescription.sdp }));
}

unmuteButton.addEventListener("click", unmute);
video.addEventListener("click", () => {
  if (!unmuteButton.hidden) unmute();
});
video.addEventListener("dblclick", () => {
  if (document.fullscreenElement) document.exitFullscreen();
  else video.requestFullscreen?.();
});

connect().catch(() => finish(TEXT.failed));
