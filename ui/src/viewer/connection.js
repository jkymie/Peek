// Conexão com o Peek. Protocolo da sinalização: veja host/server.py.

import { useEffect, useState } from "react";

const STUN_SERVERS = ["stun:stun.l.google.com:19302"];
const ICE_GATHERING_TIMEOUT_MS = 3000;

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

function signalingUrl() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${location.host}${location.pathname.replace(/\/$/, "")}/ws`;
}

/**
 * Conecta ao Peek e entrega o vídeo em `videoRef`.
 *
 * Estados: "connecting" → "playing", ou um final: "ended", "full", "failed".
 */
export function useViewerConnection(videoRef) {
  const [status, setStatus] = useState("connecting");
  const [hasAudio, setHasAudio] = useState(false);

  useEffect(() => {
    const video = videoRef.current;
    let finished = false;
    const ws = new WebSocket(signalingUrl());
    const pc = new RTCPeerConnection({ iceServers: [{ urls: STUN_SERVERS }] });

    const finish = (next) => {
      if (finished) return;
      finished = true;
      setStatus(next);
      pc.close();
      ws.close();
      video.srcObject = null;
    };

    pc.addTransceiver("video", { direction: "recvonly" });
    pc.addTransceiver("audio", { direction: "recvonly" });

    const stream = new MediaStream();
    video.srcObject = stream;
    pc.addEventListener("track", (event) => {
      stream.addTrack(event.track);
      if (event.track.kind === "audio") setHasAudio(true);
    });
    const onPlaying = () => !finished && setStatus("playing");
    video.addEventListener("playing", onPlaying);

    pc.addEventListener("connectionstatechange", () => {
      if (pc.connectionState === "failed") finish("failed");
    });

    ws.addEventListener("message", async (event) => {
      const message = JSON.parse(event.data);
      if (message.type === "answer") {
        await pc.setRemoteDescription({ type: "answer", sdp: message.sdp });
      } else if (message.type === "ended") {
        finish("ended");
      } else if (message.type === "full") {
        finish("full");
      }
    });

    ws.addEventListener("close", () => {
      // Fechou sem aviso: ou o Peek foi fechado, ou a conexão caiu.
      finish(pc.connectionState === "connected" ? "ended" : "failed");
    });

    (async () => {
      await new Promise((resolve, reject) => {
        ws.addEventListener("open", resolve, { once: true });
        ws.addEventListener("error", reject, { once: true });
      });
      await pc.setLocalDescription(await pc.createOffer());
      await waitForIceGathering(pc);
      if (!finished) ws.send(JSON.stringify({ type: "offer", sdp: pc.localDescription.sdp }));
    })().catch(() => finish("failed"));

    return () => {
      // Desmontagem (inclusive a dupla montagem do StrictMode): fecha sem mudar o estado.
      finished = true;
      video.removeEventListener("playing", onPlaying);
      pc.close();
      ws.close();
    };
  }, [videoRef]);

  return { status, hasAudio };
}
