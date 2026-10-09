import React from 'react';

/**
 * Small physics glyph for a lesson card in the /tutorials catalog.
 *
 * Each lesson gets a diagram of the one idea it teaches, so the catalog is
 * scannable by picture as well as by title. Pole colours follow the same
 * convention as the lesson viewers and MotorViewport: north is red, south is
 * blue. Everything else is drawn in currentColor so the glyph inherits the
 * card's text colour and dims with the card when a lesson is unavailable.
 *
 * Presentational only — aria-hidden, because the adjacent lesson title and
 * summary already name the lesson for assistive tech.
 */

const N_FILL = '#ef4444';
const S_FILL = '#3b82f6';
const FLUX = '#22d3ee';
const ACCENT = '#f59e0b';

type GlyphProps = { className?: string };

const Frame: React.FC<React.PropsWithChildren<GlyphProps>> = ({ className, children }) => (
  <svg
    className={className}
    viewBox="0 0 72 52"
    role="presentation"
    aria-hidden="true"
    focusable="false"
    fill="none"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    {children}
  </svg>
);

/** 1 — one magnet in open air, flux arcing out of N and back into S. */
const FollowTheFlux: React.FC<GlyphProps> = ({ className }) => (
  <Frame className={className}>
    <path d="M48 22C58 14 58 8 36 8S14 14 24 22" stroke={FLUX} strokeWidth="1.6" opacity="0.9" />
    <path d="M48 30C58 38 58 44 36 44s-22-6-12-14" stroke={FLUX} strokeWidth="1.6" opacity="0.9" />
    <path d="M52 19c9-9 6-17-16-17" stroke={FLUX} strokeWidth="1.2" opacity="0.4" />
    <path d="M52 33c9 9 6 17-16 17" stroke={FLUX} strokeWidth="1.2" opacity="0.4" />
    <path d="M27 20.5l-3 2 3 2.2" stroke={FLUX} strokeWidth="1.5" opacity="0.9" />
    <rect x="23" y="21" width="13" height="10" rx="1.5" fill={S_FILL} />
    <rect x="36" y="21" width="13" height="10" rx="1.5" fill={N_FILL} />
  </Frame>
);

/** 2 — a C-core closing the loop, with the airgap that taxes the flux. */
const AirgapTax: React.FC<GlyphProps> = ({ className }) => (
  <Frame className={className}>
    <path
      d="M30 10H16a6 6 0 0 0-6 6v20a6 6 0 0 0 6 6h14"
      stroke="currentColor"
      strokeWidth="5"
      opacity="0.75"
    />
    <path d="M42 10h8a6 6 0 0 1 6 6v20a6 6 0 0 1-6 6h-8" stroke="currentColor" strokeWidth="5" opacity="0.75" />
    <rect x="30" y="6" width="6" height="8" rx="1" fill={N_FILL} />
    <rect x="30" y="38" width="6" height="8" rx="1" fill={S_FILL} />
    <path d="M39 12v28" stroke={ACCENT} strokeWidth="1.4" strokeDasharray="2 3" />
    <path d="M36 26h6" stroke={ACCENT} strokeWidth="1.6" />
    <path d="M36 23v6M42 23v6" stroke={ACCENT} strokeWidth="1.6" />
  </Frame>
);

/** 3 — current out of the page, field circling it by the right-hand rule. */
const CurrentField: React.FC<GlyphProps> = ({ className }) => (
  <Frame className={className}>
    <circle cx="36" cy="26" r="9" stroke={FLUX} strokeWidth="1.4" opacity="0.9" />
    <circle cx="36" cy="26" r="16" stroke={FLUX} strokeWidth="1.3" opacity="0.55" />
    <circle cx="36" cy="26" r="23" stroke={FLUX} strokeWidth="1.2" opacity="0.28" />
    <path d="M45 22l1.4 4.2-4.3 1" stroke={FLUX} strokeWidth="1.4" opacity="0.9" />
    <circle cx="36" cy="26" r="5.5" fill={ACCENT} />
    <circle cx="36" cy="26" r="2" fill="#1a1206" />
  </Frame>
);

/** 4 — the B–H curve bending over at the knee. */
const IronSaturation: React.FC<GlyphProps> = ({ className }) => (
  <Frame className={className}>
    <path d="M8 44h56" stroke="currentColor" strokeWidth="1" opacity="0.35" />
    <path d="M8 44V8" stroke="currentColor" strokeWidth="1" opacity="0.35" />
    <path d="M8 44C20 44 27 30 31 20" stroke={ACCENT} strokeWidth="2.2" />
    <path d="M31 20c4-9 14-8 33-7" stroke={ACCENT} strokeWidth="2.2" opacity="0.55" />
    <circle cx="31" cy="20" r="3" fill="none" stroke={N_FILL} strokeWidth="1.8" />
    <path d="M31 20v18" stroke={N_FILL} strokeWidth="1" strokeDasharray="2 3" opacity="0.7" />
  </Frame>
);

/** 5 — F = BIL: current across a field, force pushing out of it. */
const FieldForce: React.FC<GlyphProps> = ({ className }) => (
  <Frame className={className}>
    <rect x="6" y="8" width="10" height="36" rx="1.5" fill={N_FILL} opacity="0.85" />
    <rect x="56" y="8" width="10" height="36" rx="1.5" fill={S_FILL} opacity="0.85" />
    <path d="M20 17h32M20 26h32M20 35h32" stroke={FLUX} strokeWidth="1.2" opacity="0.5" />
    <circle cx="36" cy="26" r="5" fill={ACCENT} />
    <circle cx="36" cy="26" r="1.7" fill="#1a1206" />
    <path d="M36 19V8" stroke="#84cc16" strokeWidth="2.2" />
    <path d="M32.5 11.5L36 7l3.5 4.5" stroke="#84cc16" strokeWidth="2.2" />
  </Frame>
);

/** 6 — rotor arrow lagging the field target it is being pulled toward. */
const RotorChase: React.FC<GlyphProps> = ({ className }) => (
  <Frame className={className}>
    <circle cx="36" cy="26" r="18" stroke="currentColor" strokeWidth="1.3" opacity="0.4" />
    <path d="M36 26l16-7" stroke={FLUX} strokeWidth="2.2" opacity="0.85" />
    <circle cx="53" cy="18.5" r="2.6" fill={FLUX} />
    <path d="M36 26l11 11" stroke={ACCENT} strokeWidth="2.6" />
    <path d="M42.5 36.5l5 1 1-5" stroke={ACCENT} strokeWidth="2.2" />
    <path d="M48 22a13 13 0 0 1-3.5 12" stroke="#84cc16" strokeWidth="1.5" strokeDasharray="2.5 2.5" />
    <circle cx="36" cy="26" r="3.4" fill="currentColor" opacity="0.75" />
  </Frame>
);

/** 7 — two perpendicular winding axes summing to a rotating vector. */
const RotatingField: React.FC<GlyphProps> = ({ className }) => (
  <Frame className={className}>
    <circle cx="36" cy="26" r="18" stroke="currentColor" strokeWidth="1.2" opacity="0.35" />
    <path d="M18 26h36" stroke="currentColor" strokeWidth="1.2" opacity="0.4" strokeDasharray="3 3" />
    <path d="M36 8v36" stroke="currentColor" strokeWidth="1.2" opacity="0.4" strokeDasharray="3 3" />
    <path d="M36 26l13-13" stroke={ACCENT} strokeWidth="2.6" />
    <path d="M43 12h7v7" stroke={ACCENT} strokeWidth="2.2" />
    <path d="M50 32a16 16 0 0 1-9 10" stroke={FLUX} strokeWidth="1.6" />
    <path d="M39 39l2 4 4-2" stroke={FLUX} strokeWidth="1.6" />
  </Frame>
);

/** 8 — three balanced phases, 120 degrees apart. */
const ThreePhase: React.FC<GlyphProps> = ({ className }) => {
  const wave = (shift: number) => {
    let d = '';
    for (let x = 0; x <= 64; x += 2) {
      const y = 26 - Math.sin(((x / 64) * 2 * Math.PI) + shift) * 14;
      d += x === 0 ? `M4 ${y.toFixed(1)}` : ` L${(x + 4).toFixed(1)} ${y.toFixed(1)}`;
    }
    return d;
  };
  return (
    <Frame className={className}>
      <path d="M4 26h64" stroke="currentColor" strokeWidth="1" opacity="0.3" />
      <path d={wave(0)} stroke={N_FILL} strokeWidth="1.9" />
      <path d={wave((2 * Math.PI) / 3)} stroke="#84cc16" strokeWidth="1.9" />
      <path d={wave((4 * Math.PI) / 3)} stroke={S_FILL} strokeWidth="1.9" />
    </Frame>
  );
};

/** 9 — the first complete machine: six wound teeth round a two-pole rotor. */
const MotorAssembly: React.FC<GlyphProps> = ({ className }) => {
  const teeth = [0, 60, 120, 180, 240, 300];
  return (
    <Frame className={className}>
      <circle cx="36" cy="26" r="21" stroke="currentColor" strokeWidth="1.4" opacity="0.55" />
      <circle cx="36" cy="26" r="14.5" stroke="currentColor" strokeWidth="1" opacity="0.35" />
      {teeth.map((deg) => {
        const rad = (deg * Math.PI) / 180;
        const x1 = 36 + Math.cos(rad) * 14.5;
        const y1 = 26 + Math.sin(rad) * 14.5;
        const x2 = 36 + Math.cos(rad) * 20;
        const y2 = 26 + Math.sin(rad) * 20;
        return (
          <path
            key={deg}
            d={`M${x1.toFixed(1)} ${y1.toFixed(1)}L${x2.toFixed(1)} ${y2.toFixed(1)}`}
            stroke={ACCENT}
            strokeWidth="4"
            opacity="0.8"
          />
        );
      })}
      <path d="M25.5 26a10.5 10.5 0 0 1 21 0z" fill={N_FILL} opacity="0.9" />
      <path d="M46.5 26a10.5 10.5 0 0 1-21 0z" fill={S_FILL} opacity="0.9" />
      <circle cx="36" cy="26" r="2.6" fill="#0f1115" stroke="currentColor" strokeWidth="1" />
    </Frame>
  );
};

/** 10 — BEMF rising with speed until it meets the inverter voltage ceiling. */
const BackEmfHeadroom: React.FC<GlyphProps> = ({ className }) => {
  let d = '';
  for (let x = 0; x <= 60; x += 2) {
    const envelope = 3 + (x / 60) * 15;
    const y = 30 - Math.sin((x / 60) * 4 * Math.PI) * envelope;
    d += x === 0 ? `M6 ${y.toFixed(1)}` : ` L${(x + 6).toFixed(1)} ${y.toFixed(1)}`;
  }
  return (
    <Frame className={className}>
      <path d="M6 30h60" stroke="currentColor" strokeWidth="1" opacity="0.3" />
      <path d="M6 11h60" stroke={N_FILL} strokeWidth="1.4" strokeDasharray="4 3" opacity="0.9" />
      <path d={d} stroke={ACCENT} strokeWidth="1.9" />
      <path d="M60 44V34" stroke={FLUX} strokeWidth="1.3" opacity="0.8" />
      <path d="M57.5 36.5L60 33l2.5 3.5" stroke={FLUX} strokeWidth="1.3" opacity="0.8" />
    </Frame>
  );
};

/** ★ — the guided tour of the real workspace, not a primer lesson. */
const GuidedTour: React.FC<GlyphProps> = ({ className }) => (
  <Frame className={className}>
    <rect x="8" y="9" width="56" height="34" rx="3" stroke="currentColor" strokeWidth="1.4" opacity="0.5" />
    <path d="M8 17h56" stroke="currentColor" strokeWidth="1.2" opacity="0.4" />
    <circle cx="13" cy="13" r="1.4" fill="currentColor" opacity="0.6" />
    <circle cx="18" cy="13" r="1.4" fill="currentColor" opacity="0.6" />
    <circle cx="30" cy="30" r="8" stroke={ACCENT} strokeWidth="2" />
    <path d="M36 36l8 7" stroke={ACCENT} strokeWidth="2.4" />
    <path d="M50 22l1.6 4.4L56 28l-4.4 1.6L50 34l-1.6-4.4L44 28l4.4-1.6z" fill={FLUX} opacity="0.9" />
  </Frame>
);

/** Section review — separate threads of the part converging into one idea. */
const SectionReview: React.FC<GlyphProps> = ({ className }) => (
  <Frame className={className}>
    <path d="M10 10h10c12 0 12 16 24 16" stroke={FLUX} strokeWidth="1.5" opacity="0.7" />
    <path d="M10 26h34" stroke="#84cc16" strokeWidth="1.5" opacity="0.7" />
    <path d="M10 42h10c12 0 12-16 24-16" stroke={N_FILL} strokeWidth="1.5" opacity="0.7" />
    <circle cx="10" cy="10" r="2.6" fill={FLUX} opacity="0.9" />
    <circle cx="10" cy="26" r="2.6" fill="#84cc16" opacity="0.9" />
    <circle cx="10" cy="42" r="2.6" fill={N_FILL} opacity="0.9" />
    <circle cx="50" cy="26" r="8" stroke={ACCENT} strokeWidth="2" />
    <path d="M46.5 26l2.6 2.8 5-6" stroke={ACCENT} strokeWidth="2" />
  </Frame>
);

const GLYPHS: Record<string, React.FC<GlyphProps>> = {
  'follow-the-flux': FollowTheFlux,
  'airgap-tax': AirgapTax,
  'current-field': CurrentField,
  'iron-saturation': IronSaturation,
  'field-force': FieldForce,
  'rotor-chase': RotorChase,
  'rotating-field': RotatingField,
  'three-phase-motor': ThreePhase,
  'motor-magnetic-circuit': MotorAssembly,
  'back-emf-voltage-headroom': BackEmfHeadroom,
  'guided-first-solve': GuidedTour,
  'section-review': SectionReview,
};

export const LessonGlyph: React.FC<{ lessonId: string; className?: string }> = ({
  lessonId,
  className,
}) => {
  const Glyph = GLYPHS[lessonId];
  if (!Glyph) return null;
  return <Glyph className={className} />;
};
