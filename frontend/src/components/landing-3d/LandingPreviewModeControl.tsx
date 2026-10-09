import type { PointerEvent } from 'react';

export type LandingPreviewMode = 'geometry' | 'mesh' | 'field';

const PREVIEW_MODES: ReadonlyArray<{ id: LandingPreviewMode; label: string }> = [
  { id: 'geometry', label: 'Geometry' },
  { id: 'mesh', label: 'Mesh' },
  { id: 'field', label: 'Field' },
];

interface LandingPreviewModeControlProps {
  activeMode: LandingPreviewMode;
  ariaLabel: string;
  onSelect: (mode: LandingPreviewMode) => void;
  disabledModes?: readonly LandingPreviewMode[];
}

export function LandingPreviewModeControl({
  activeMode,
  ariaLabel,
  onSelect,
  disabledModes = [],
}: LandingPreviewModeControlProps) {
  const stopPointerEvent = (event: PointerEvent<HTMLDivElement>) => event.stopPropagation();

  return (
    <div
      className="landing-preview-mode-control"
      role="group"
      aria-label={ariaLabel}
      onPointerDown={stopPointerEvent}
      onPointerUp={stopPointerEvent}
      onPointerCancel={stopPointerEvent}
    >
      {PREVIEW_MODES.map((mode) => (
        <button
          key={mode.id}
          type="button"
          className={mode.id === activeMode ? 'is-active' : ''}
          aria-pressed={mode.id === activeMode}
          disabled={disabledModes.includes(mode.id)}
          onClick={() => onSelect(mode.id)}
        >
          {mode.label}
        </button>
      ))}
    </div>
  );
}
