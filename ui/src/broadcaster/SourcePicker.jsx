import { MonitorIcon, WindowIcon } from "../shared/icons.jsx";

// Lista de telas e janelas, separadas em dois grupos. Duplo clique confirma.
export default function SourcePicker({ sources, value, onChange, onConfirm, texts, current }) {
  const groups = [
    { kind: "monitor", title: texts.SCREENS_GROUP, Icon: MonitorIcon },
    { kind: "window", title: texts.WINDOWS_GROUP, Icon: WindowIcon },
  ];

  if (sources.length === 0) {
    return <p className="empty">{texts.NO_SOURCES}</p>;
  }

  return (
    <div className="sources" role="radiogroup" aria-label={texts.CHOOSE_TITLE}>
      {groups.map(({ kind, title, Icon }) => {
        const items = sources.filter((s) => s.kind === kind);
        if (items.length === 0) return null;
        return (
          <section key={kind} className="source-group">
            <h3 className="group-title">{title}</h3>
            {items.map((source) => (
              <label
                key={source.key}
                className="source"
                data-selected={source.key === value || undefined}
                title={source.label}
                onDoubleClick={() => onConfirm?.(source.key)}
              >
                <input
                  type="radio"
                  name="source"
                  className="visually-hidden"
                  value={source.key}
                  checked={source.key === value}
                  onChange={() => onChange(source.key)}
                />
                <span className="source-icon">
                  <Icon />
                </span>
                <span className="source-text">
                  <span className="source-title">{source.title}</span>
                  {source.detail && <span className="source-detail">{source.detail}</span>}
                </span>
                {source.key === current && <span className="tag">{texts.LIVE_BADGE}</span>}
              </label>
            ))}
          </section>
        );
      })}
    </div>
  );
}
