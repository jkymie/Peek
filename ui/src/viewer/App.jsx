import { useCallback, useEffect, useRef, useState } from "react";
import { FullscreenIcon, VolumeIcon } from "../shared/icons.jsx";
import { useViewerConnection } from "./connection.js";

const TEXT = {
  connecting: "Conectando…",
  ended: "A transmissão terminou.",
  full: "Já tem muita gente assistindo. Tente de novo daqui a pouco.",
  failed: "Não foi possível conectar. Tente outro navegador ou outra rede.",
  unmute: "Clique para ativar o som",
  mute: "Tirar o som",
  unmuteShort: "Ativar o som",
  volume: "Volume",
  fullscreen: "Tela cheia",
  exitFullscreen: "Sair da tela cheia",
};

const CONTROLS_HIDE_MS = 2500;
const VOLUME_STEP = 0.1;
const VOLUME_KEY = "peek.volume";

function loadVolume() {
  try {
    const saved = Number.parseFloat(localStorage.getItem(VOLUME_KEY));
    return Number.isFinite(saved) ? Math.min(1, Math.max(0, saved)) : 1;
  } catch {
    return 1;
  }
}

function saveVolume(volume) {
  try {
    localStorage.setItem(VOLUME_KEY, String(volume));
  } catch {
    // Sem armazenamento (aba anônima, por exemplo): só não lembra o volume.
  }
}

const fullscreenElement = () => document.fullscreenElement ?? document.webkitFullscreenElement;

export default function App() {
  const stageRef = useRef(null);
  const videoRef = useRef(null);
  const { status, hasAudio } = useViewerConnection(videoRef);
  const playing = status === "playing";

  // O navegador só deixa o vídeo começar sozinho se estiver sem som.
  const [muted, setMuted] = useState(true);
  const [askedToUnmute, setAskedToUnmute] = useState(false);
  const [volume, setVolume] = useState(loadVolume);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [controlsVisible, setControlsVisible] = useState(true);
  const hideTimer = useRef(null);
  const controlsRef = useRef(null);

  const needsUnmute = playing && hasAudio && muted && !askedToUnmute;

  // --- som --------------------------------------------------------------------

  useEffect(() => {
    const video = videoRef.current;
    video.volume = volume;
    video.muted = muted;
    if (!muted) video.play().catch(() => {});
  }, [volume, muted]);

  const unmute = useCallback(() => {
    setAskedToUnmute(true);
    setMuted(false);
    setVolume((v) => (v === 0 ? 0.5 : v));
  }, []);

  const toggleMute = useCallback(() => {
    if (muted || volume === 0) unmute();
    else setMuted(true);
  }, [muted, volume, unmute]);

  const changeVolume = useCallback((next) => {
    const value = Math.round(Math.min(1, Math.max(0, next)) * 100) / 100;
    setVolume(value);
    setMuted(value === 0);
    setAskedToUnmute(true);
    saveVolume(value);
  }, []);

  // --- tela cheia -------------------------------------------------------------

  useEffect(() => {
    const update = () => setIsFullscreen(Boolean(fullscreenElement()));
    document.addEventListener("fullscreenchange", update);
    document.addEventListener("webkitfullscreenchange", update);
    return () => {
      document.removeEventListener("fullscreenchange", update);
      document.removeEventListener("webkitfullscreenchange", update);
    };
  }, []);

  const toggleFullscreen = useCallback(() => {
    if (fullscreenElement()) {
      (document.exitFullscreen ?? document.webkitExitFullscreen)?.call(document);
      return;
    }
    const stage = stageRef.current;
    const request = stage.requestFullscreen ?? stage.webkitRequestFullscreen;
    if (request) request.call(stage)?.catch?.(() => {});
    else videoRef.current.webkitEnterFullscreen?.(); // iPhone: só o vídeo vai para tela cheia
  }, []);

  // --- controles que somem sozinhos -------------------------------------------

  const showControls = useCallback(() => {
    setControlsVisible(true);
    clearTimeout(hideTimer.current);
    hideTimer.current = setTimeout(() => {
      // Continuam visíveis enquanto o mouse ou o foco do teclado estiverem neles.
      const controls = controlsRef.current;
      if (controls?.matches(":hover") || controls?.contains(document.activeElement)) {
        showControls();
      } else {
        setControlsVisible(false);
      }
    }, CONTROLS_HIDE_MS);
  }, []);

  useEffect(() => {
    if (playing) showControls();
    return () => clearTimeout(hideTimer.current);
  }, [playing, showControls]);

  // --- teclado: F = tela cheia, M = som, ↑/↓ = volume -------------------------

  useEffect(() => {
    const onKey = (event) => {
      if (!playing || event.ctrlKey || event.altKey || event.metaKey) return;
      const onSlider = event.target instanceof HTMLInputElement;
      const key = event.key.toLowerCase();
      if (key === "f") toggleFullscreen();
      else if (key === "m") toggleMute();
      else if (key === "arrowup" && !onSlider) changeVolume((muted ? 0 : volume) + VOLUME_STEP);
      else if (key === "arrowdown" && !onSlider) changeVolume(volume - VOLUME_STEP);
      else return;
      event.preventDefault();
      showControls();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [playing, muted, volume, toggleFullscreen, toggleMute, changeVolume, showControls]);

  // --- tela -------------------------------------------------------------------

  const onVideoClick = () => {
    if (needsUnmute) unmute();
    else showControls();
  };

  const level = muted ? 0 : volume;
  const message = playing ? "" : TEXT[status];
  const hidden = playing && !controlsVisible && !needsUnmute;

  return (
    <main
      ref={stageRef}
      className="stage"
      data-idle={hidden || undefined}
      onPointerMove={playing ? showControls : undefined}
    >
      <video
        ref={videoRef}
        autoPlay
        playsInline
        muted
        onClick={onVideoClick}
        onDoubleClick={toggleFullscreen}
      />

      {message && (
        <p className="status" role="status">
          {status === "connecting" && <span className="spinner" aria-hidden="true" />}
          {message}
        </p>
      )}

      {needsUnmute && (
        <button type="button" className="unmute" onClick={unmute}>
          <VolumeIcon level={1} size={20} /> {TEXT.unmute}
        </button>
      )}

      {playing && (
        <div ref={controlsRef} className="controls" data-hidden={hidden || undefined}>
          <div className="volume">
            <button
              type="button"
              className="control"
              onClick={toggleMute}
              aria-label={level === 0 ? TEXT.unmuteShort : TEXT.mute}
              title={level === 0 ? TEXT.unmuteShort : TEXT.mute}
            >
              <VolumeIcon level={level} />
            </button>
            <input
              type="range"
              className="slider"
              min="0"
              max="1"
              step="0.01"
              value={level}
              onChange={(e) => changeVolume(Number(e.target.value))}
              aria-label={TEXT.volume}
              aria-valuetext={`${Math.round(level * 100)}%`}
              style={{ "--level": `${level * 100}%` }}
            />
          </div>
          <button
            type="button"
            className="control"
            onClick={toggleFullscreen}
            aria-label={isFullscreen ? TEXT.exitFullscreen : TEXT.fullscreen}
            title={isFullscreen ? TEXT.exitFullscreen : TEXT.fullscreen}
          >
            <FullscreenIcon exit={isFullscreen} />
          </button>
        </div>
      )}
    </main>
  );
}
