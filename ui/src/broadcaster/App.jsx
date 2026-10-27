import { useEffect, useRef, useState } from "react";
import {
  AlertIcon,
  CheckIcon,
  CopyIcon,
  EyeIcon,
  RefreshIcon,
  StopIcon,
  SwapIcon,
} from "../shared/icons.jsx";
import { connectBridge } from "./bridge.js";
import QualityPicker from "./QualityPicker.jsx";
import SourcePicker from "./SourcePicker.jsx";

const LINK_COPIED_MS = 2000;
const NOTICE_MS = 4000;

export default function App() {
  const [state, setState] = useState(null);
  const [peek, setPeek] = useState(null);
  const [failure, setFailure] = useState("");

  useEffect(() => {
    connectBridge(setState).then(setPeek, (error) => setFailure(error.message));
  }, []);

  if (failure) return <main className="screen center"><p>{failure}</p></main>;
  if (!state || !peek) return null;

  const props = { state, peek, texts: state.texts };
  return (
    <>
      {state.screen === "choose" && <ChooseScreen {...props} />}
      {state.screen === "preparing" && <PreparingScreen {...props} />}
      {state.screen === "live" && <LiveScreen {...props} />}
      {state.screen === "error" && <ErrorScreen {...props} />}
      <Notice notice={state.notice} />
    </>
  );
}

// --- Escolher -------------------------------------------------------------------

function useSelectedSource(sources, preferred) {
  const [selected, setSelected] = useState(preferred);
  // Mantém a escolha se ela ainda existir depois de "Atualizar lista"; se não, a primeira
  // (tela principal: o caso mais comum).
  const valid = sources.some((s) => s.key === selected) ? selected : sources[0]?.key ?? null;
  return [valid, setSelected];
}

function ChooseScreen({ state, peek, texts }) {
  const [source, setSource] = useSelectedSource(state.sources, null);
  const [quality, setQuality] = useState(state.defaultQuality);
  const selected = state.sources.find((s) => s.key === source);
  const start = (key = source) => key && peek.start(key, quality);

  return (
    <main className="screen">
      <header className="header">
        <h1>{texts.CHOOSE_TITLE}</h1>
        <button type="button" className="button ghost" onClick={() => peek.refreshSources()}>
          <RefreshIcon size={16} /> {texts.REFRESH}
        </button>
      </header>

      <div className="scroll-area">
        <SourcePicker
          sources={state.sources}
          value={source}
          onChange={setSource}
          onConfirm={start}
          texts={texts}
        />
      </div>

      {selected?.kind === "monitor" && <p className="reminder">{texts.FULL_SCREEN_REMINDER}</p>}

      <section className="section">
        <h2>{texts.QUALITY_TITLE}</h2>
        <QualityPicker
          qualities={state.qualities}
          value={quality}
          onChange={setQuality}
          label={texts.QUALITY_TITLE}
        />
      </section>

      <footer className="footer">
        <button
          type="button"
          className="button primary large"
          disabled={!source}
          onClick={() => start()}
        >
          {texts.START}
        </button>
      </footer>
    </main>
  );
}

// --- Preparando -----------------------------------------------------------------

function PreparingScreen({ texts }) {
  return (
    <main className="screen center" aria-busy="true">
      <div className="spinner" aria-hidden="true" />
      <h1>{texts.PREPARING}</h1>
    </main>
  );
}

// --- Transmitindo ---------------------------------------------------------------

function LiveScreen({ state, peek, texts }) {
  const [copied, setCopied] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [pendingQuality, setPendingQuality] = useState(null);
  const busy = state.busy !== null;

  useEffect(() => {
    if (!copied) return undefined;
    const timer = setTimeout(() => setCopied(false), LINK_COPIED_MS);
    return () => clearTimeout(timer);
  }, [copied]);

  useEffect(() => {
    if (state.busy !== "quality") setPendingQuality(null);
  }, [state.busy]);

  const copy = () => {
    peek.copyLink();
    setCopied(true);
  };

  const changeQuality = (id) => {
    setPendingQuality(id);
    peek.setQuality(id);
  };

  return (
    <main className="screen">
      <header className="header">
        <div>
          <span className="live-badge">
            <span className="live-dot" aria-hidden="true" /> {texts.LIVE_BADGE}
          </span>
          <h1>{texts.LIVE_TITLE}</h1>
        </div>
        <span className="viewers" role="status" data-active={state.viewers > 0 || undefined}>
          <EyeIcon size={18} /> {state.viewersText}
        </span>
      </header>

      <div className="scroll-area live">
        <section className="card showing">
          <div className="showing-text">
            <span className="muted">{texts.LIVE_SOURCE.replace("{name}", "")}</span>
            <strong title={state.liveSourceLabel}>{state.liveSourceLabel}</strong>
          </div>
          <button
            type="button"
            className="button secondary"
            disabled={busy}
            onClick={() => {
              peek.refreshSources();
              setSwitching(true);
            }}
          >
            <SwapIcon size={16} /> {state.busy === "source" ? texts.SWITCHING : texts.SWITCH_SOURCE}
          </button>
        </section>

        <section className="card">
          <h2>{texts.LINK_TITLE}</h2>
          <div className="link-row">
            <input
              className="link"
              readOnly
              value={state.link}
              aria-label={texts.LINK_TITLE}
              onFocus={(e) => e.target.select()}
            />
            <button type="button" className="button primary copy" onClick={copy}>
              {copied ? <CheckIcon size={16} /> : <CopyIcon size={16} />}
              {copied ? texts.LINK_COPIED : texts.COPY_LINK}
            </button>
          </div>
          <p className="muted small">{texts.SHARE_HINT}</p>
          {state.localOnly && <p className="muted small">{texts.LOCAL_NETWORK_HINT}</p>}
        </section>

        <section className="section">
          <div className="section-head">
            <h2>{texts.QUALITY_TITLE}</h2>
            <span className="muted small">{texts.QUALITY_LIVE_HINT}</span>
          </div>
          <QualityPicker
            qualities={state.qualities}
            value={pendingQuality ?? state.quality}
            pending={pendingQuality}
            disabled={busy}
            onChange={changeQuality}
            label={texts.QUALITY_TITLE}
          />
        </section>
      </div>

      <footer className="footer">
        <button type="button" className="button danger large" onClick={() => peek.stop()}>
          <StopIcon size={18} /> {texts.STOP}
        </button>
      </footer>

      {switching && (
        <SwitchDialog state={state} peek={peek} texts={texts} onClose={() => setSwitching(false)} />
      )}
    </main>
  );
}

function SwitchDialog({ state, peek, texts, onClose }) {
  const [source, setSource] = useSelectedSource(state.sources, state.liveSource);
  const started = useRef(false);
  const dialog = useRef(null);
  const working = state.busy === "source";

  // Fecha sozinho quando a troca termina (deu certo ou não; o aviso explica).
  useEffect(() => {
    if (working) started.current = true;
    else if (started.current) onClose();
  }, [working, onClose]);

  useEffect(() => {
    const element = dialog.current;
    element.showModal();
    return () => element.close();
  }, []);

  const confirm = (key = source) => {
    if (key && key !== state.liveSource && !working) peek.switchSource(key);
  };

  return (
    <dialog
      ref={dialog}
      className="dialog"
      aria-labelledby="switch-title"
      onCancel={(e) => {
        e.preventDefault();
        if (!working) onClose();
      }}
    >
      <header className="header">
        <h1 id="switch-title">{texts.SWITCH_TITLE}</h1>
        <button type="button" className="button ghost" onClick={() => peek.refreshSources()}>
          <RefreshIcon size={16} /> {texts.REFRESH}
        </button>
      </header>
      <div className="scroll-area">
        <SourcePicker
          sources={state.sources}
          value={source}
          onChange={setSource}
          onConfirm={confirm}
          texts={texts}
          current={state.liveSource}
        />
      </div>
      {state.sources.find((s) => s.key === source)?.kind === "monitor" && (
        <p className="reminder">{texts.FULL_SCREEN_REMINDER}</p>
      )}
      <footer className="footer row">
        <button type="button" className="button secondary" disabled={working} onClick={onClose}>
          {texts.CANCEL}
        </button>
        <button
          type="button"
          className="button primary"
          disabled={!source || source === state.liveSource || working}
          onClick={() => confirm()}
        >
          {working ? texts.SWITCHING : texts.SWITCH_CONFIRM}
        </button>
      </footer>
    </dialog>
  );
}

// --- Erro -----------------------------------------------------------------------

function ErrorScreen({ state, peek, texts }) {
  return (
    <main className="screen center">
      <span className="error-icon">
        <AlertIcon size={40} />
      </span>
      <h1>{texts.ERROR_TITLE}</h1>
      <p className="error-text">{state.error}</p>
      <button type="button" className="button primary large" onClick={() => peek.backToChoose()}>
        {texts.TRY_AGAIN}
      </button>
    </main>
  );
}

// --- Avisos rápidos ("Qualidade trocada", "Não foi possível...") -----------------

function Notice({ notice }) {
  const [visible, setVisible] = useState(null);

  useEffect(() => {
    if (!notice) return undefined;
    setVisible(notice);
    const timer = setTimeout(() => setVisible(null), NOTICE_MS);
    return () => clearTimeout(timer);
  }, [notice?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!visible) return null;
  return (
    <div className="notice" role="status" data-error={visible.error || undefined}>
      {visible.error ? <AlertIcon size={18} /> : <CheckIcon size={18} />}
      {visible.text}
    </div>
  );
}
