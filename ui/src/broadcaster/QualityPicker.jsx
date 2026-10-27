// Opções de qualidade: nome do dia a dia + resolução e FPS + frase curta.
export default function QualityPicker({ qualities, value, onChange, disabled, pending, label }) {
  return (
    <div className="qualities" role="radiogroup" aria-label={label}>
      {qualities.map((q) => (
        <label
          key={q.id}
          className="quality"
          data-selected={q.id === value || undefined}
          data-pending={q.id === pending || undefined}
          data-disabled={disabled || undefined}
        >
          <input
            type="radio"
            name="quality"
            className="visually-hidden"
            value={q.id}
            checked={q.id === value}
            disabled={disabled}
            onChange={() => onChange(q.id)}
          />
          <span className="quality-head">
            <span className="quality-name">{q.name}</span>
            <span className="quality-details">{q.details}</span>
          </span>
          <span className="quality-description">{q.description}</span>
        </label>
      ))}
    </div>
  );
}
