// Ícones em SVG (sem dependências externas). Herdam a cor do texto.

function Icon({ children, size = 20, ...props }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      {children}
    </svg>
  );
}

export const MonitorIcon = (p) => (
  <Icon {...p}>
    <rect x="2" y="3" width="20" height="14" rx="2" />
    <path d="M8 21h8M12 17v4" />
  </Icon>
);

export const WindowIcon = (p) => (
  <Icon {...p}>
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <path d="M3 9h18M7 6.5h.01M10 6.5h.01" />
  </Icon>
);

export const RefreshIcon = (p) => (
  <Icon {...p}>
    <path d="M21 12a9 9 0 1 1-2.64-6.36L21 8" />
    <path d="M21 3v5h-5" />
  </Icon>
);

export const CopyIcon = (p) => (
  <Icon {...p}>
    <rect x="9" y="9" width="12" height="12" rx="2" />
    <path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1" />
  </Icon>
);

export const CheckIcon = (p) => (
  <Icon {...p}>
    <path d="M20 6 9 17l-5-5" />
  </Icon>
);

export const EyeIcon = (p) => (
  <Icon {...p}>
    <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" />
    <circle cx="12" cy="12" r="3" />
  </Icon>
);

export const SwapIcon = (p) => (
  <Icon {...p}>
    <path d="M7 4 3 8l4 4M3 8h14M17 20l4-4-4-4M21 16H7" />
  </Icon>
);

export const StopIcon = (p) => (
  <Icon {...p}>
    <rect x="6" y="6" width="12" height="12" rx="2" />
  </Icon>
);

export const AlertIcon = (p) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="10" />
    <path d="M12 8v4M12 16h.01" />
  </Icon>
);

export const VolumeIcon = ({ level, ...p }) => (
  <Icon {...p}>
    <path d="M11 5 6 9H2v6h4l5 4V5Z" />
    {level === 0 ? (
      <path d="m23 9-6 6M17 9l6 6" />
    ) : (
      <>
        <path d="M15.5 8.5a5 5 0 0 1 0 7" />
        {level > 0.5 && <path d="M19 5a10 10 0 0 1 0 14" />}
      </>
    )}
  </Icon>
);

export const FullscreenIcon = ({ exit, ...p }) => (
  <Icon {...p}>
    {exit ? (
      <path d="M8 3v3a2 2 0 0 1-2 2H3M21 8h-3a2 2 0 0 1-2-2V3M3 16h3a2 2 0 0 1 2 2v3M16 21v-3a2 2 0 0 1 2-2h3" />
    ) : (
      <path d="M8 3H5a2 2 0 0 0-2 2v3M21 8V5a2 2 0 0 0-2-2h-3M3 16v3a2 2 0 0 0 2 2h3M16 21h3a2 2 0 0 0 2-2v-3" />
    )}
  </Icon>
);
