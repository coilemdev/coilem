import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type ReactNode,
} from 'react';

import {
  fetchLinearHalbachMesh,
  fetchLinearHalbachPreview,
  streamLinearHalbachSolve,
  validateLinearHalbach,
} from './api';
import { migrateProjectFile, COILEM_SCHEMA_VERSION } from '../../api/projectSchema';
import { DESIGN_FILE_ACCEPT, DESIGN_FILE_EXTENSION, designFileBaseName } from '../designFile';
import {
  LinearHalbach2DViewport,
  type LinearHalbachResultView,
  type LinearHalbachViewportMode,
} from './LinearHalbach2DViewport';
import { LinearHalbach3DViewer } from './LinearHalbach3DViewer';
import {
  cloneDefaultLinearHalbachConfig,
  type HalbachSolveProgress,
  LINEAR_HALBACH_MODEL_NOTICE,
  type LinearHalbachArrayConfig,
  type LinearHalbachMeshPreview,
  type LinearHalbachPreview,
  type LinearHalbachProjectFile,
  type LinearHalbachReport,
  withLinearHalbachQualityPreset,
} from './types';
import './halbach.css';

type WorkflowStage = 'design' | 'solve' | 'report';
type HalbachTopology = 'cylindrical' | 'linear';
type ViewDimension = '2d' | '3d';

interface LinearHalbachWorkspaceProps {
  onHome: () => void;
  onTopologyChange: (topology: HalbachTopology) => void;
  initialConfig?: LinearHalbachArrayConfig;
  connectionStatus?: 'checking' | 'online' | 'offline';
}

interface ValidationIssue {
  code?: string;
  field: string;
  message: string;
}

interface NumberInputProps {
  label: string;
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
  suffix?: string;
  disabled?: boolean;
}

function NumberInput({
  label,
  value,
  onChange,
  min,
  max,
  step = 1,
  suffix,
  disabled = false,
}: NumberInputProps) {
  return (
    <label className="halbach-field">
      <span>{label}</span>
      <span className="halbach-input-shell">
        <input
          type="number"
          value={Number.isFinite(value) ? value : ''}
          min={min}
          max={max}
          step={step}
          disabled={disabled}
          onChange={(event) => onChange(event.target.valueAsNumber)}
        />
        {suffix && <small>{suffix}</small>}
      </span>
    </label>
  );
}

function ParameterGroup({
  title,
  children,
  defaultOpen = true,
}: {
  title: string;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  return (
    <details className="halbach-parameter-group" open={defaultOpen}>
      <summary>{title}</summary>
      <div className="halbach-parameter-body">{children}</div>
    </details>
  );
}

function formatMetric(
  value: number | null | undefined,
  unit = '',
  digits = 4,
): string {
  if (value == null || !Number.isFinite(value)) return 'Unavailable';
  return `${value.toLocaleString(undefined, {
    maximumSignificantDigits: digits,
  })}${unit ? ` ${unit}` : ''}`;
}

function patchSection(
  config: LinearHalbachArrayConfig,
  section: 'geometry' | 'array' | 'sample_region',
  field: string,
  value: unknown,
): LinearHalbachArrayConfig {
  const next = structuredClone(config);
  const record = next as unknown as Record<string, Record<string, unknown>>;
  record[section][field] = value;
  return next;
}

function patchSolve(
  config: LinearHalbachArrayConfig,
  field: string,
  value: unknown,
): LinearHalbachArrayConfig {
  const next = structuredClone(config);
  const solve = (next as unknown as { solve: Record<string, unknown> }).solve;
  solve[field] = value;
  return next;
}

function patchMesh(
  config: LinearHalbachArrayConfig,
  field: string,
  value: unknown,
): LinearHalbachArrayConfig {
  const next = structuredClone(config);
  next.solve.quality = 'custom';
  const mesh = (
    next as unknown as { solve: { mesh: Record<string, unknown> } }
  ).solve.mesh;
  mesh[field] = value;
  return next;
}

function patchMagnet(
  config: LinearHalbachArrayConfig,
  values: Record<string, unknown>,
): LinearHalbachArrayConfig {
  const next = structuredClone(config);
  const holder = next as unknown as { magnet: Record<string, unknown> };
  holder.magnet = { ...holder.magnet, ...values };
  return next;
}

function collectLocalErrors(config: LinearHalbachArrayConfig): ValidationIssue[] {
  const errors: ValidationIssue[] = [];
  const add = (field: string, message: string) => errors.push({ field, message });
  const { geometry, sample_region: sample } = config;
  if (!(geometry.block_width > 0)) add('geometry.block_width', 'Magnet width must be greater than zero.');
  if (!(geometry.magnet_height > 0)) add('geometry.magnet_height', 'Magnet height must be greater than zero.');
  if (!(geometry.out_of_plane_depth > 0)) {
    add('geometry.out_of_plane_depth', 'Out-of-plane depth must be greater than zero.');
  }
  if (!Number.isInteger(geometry.period_count) || geometry.period_count < 1 || geometry.period_count > 16) {
    add('geometry.period_count', 'Period count must be an integer from 1 through 16.');
  }
  if (!(geometry.block_gap >= 0 && geometry.block_gap < geometry.block_width)) {
    add('geometry.block_gap', 'Gap must be non-negative and smaller than the magnet width.');
  }
  if (!(sample.probe_offset > 0)) {
    add('sample_region.probe_offset', 'Probe offset must be greater than zero.');
  }
  if (
    !Number.isInteger(sample.edge_exclusion_periods)
    || sample.edge_exclusion_periods < 0
    || sample.edge_exclusion_periods > 7
    || 2 * sample.edge_exclusion_periods >= geometry.period_count
  ) {
    add(
      'sample_region.edge_exclusion_periods',
      'Edge exclusion must be an integer leaving at least one evaluated period.',
    );
  }
  if (
    !Number.isInteger(sample.samples_per_period)
    || sample.samples_per_period < 8
    || sample.samples_per_period > 512
  ) {
    add('sample_region.samples_per_period', 'Use 8 through 512 samples per period.');
  }
  if (config.magnet.source === 'custom') {
    if (!config.magnet.name.trim()) {
      add('magnet.name', 'Custom material name is required.');
    }
    if (!(config.magnet.remanence_t > 0)) {
      add('magnet.remanence_t', 'Remanence must be greater than zero.');
    }
    if (!(config.magnet.relative_permeability >= 1)) {
      add('magnet.relative_permeability', 'Relative permeability must be at least one.');
    }
    if (!(config.magnet.source_note ?? '').trim()) {
      add('magnet.source_note', 'A material source note is required.');
    }
  }
  if (
    config.solve.mesh.outer_padding_factor < 0.5
    || config.solve.mesh.outer_padding_factor > 10
  ) {
    add('solve.mesh.outer_padding_factor', 'Outer padding factor must be from 0.5 through 10.');
  }
  if (
    sample.probe_offset >= config.solve.mesh.outer_padding_factor
      * 4 * (geometry.block_width + geometry.block_gap)
  ) {
    add('sample_region.probe_offset', 'Probe offset must remain inside the modeled outer boundary.');
  }
  return errors;
}

function downloadBlob(body: BlobPart, filename: string, type: string): void {
  const url = URL.createObjectURL(new Blob([body], { type }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function reportNumber(report: LinearHalbachReport, ...paths: string[][]): number | null {
  const root = report as unknown as Record<string, unknown>;
  for (const path of paths) {
    let value: unknown = root;
    for (const key of path) {
      if (!value || typeof value !== 'object') {
        value = undefined;
        break;
      }
      value = (value as Record<string, unknown>)[key];
    }
    if (typeof value === 'number' && Number.isFinite(value)) return value;
  }
  return null;
}

function TopologyIcon({ topology }: { topology: HalbachTopology }) {
  if (topology === 'linear') {
    return (
      <svg viewBox="0 0 28 20" width="24" height="20" aria-hidden="true">
        {[0, 1, 2, 3].map((index) => (
          <rect
            key={index}
            x={1 + 6.7 * index}
            y="6"
            width="5.5"
            height="9"
            rx="1"
            fill={index % 2 === 0 ? '#f59e0b' : '#22d3ee'}
          />
        ))}
        <path d="M3 3h21" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        <path d="m21 1 3 2-3 2" fill="none" stroke="currentColor" strokeWidth="1.5" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
      <circle cx="12" cy="12" r="9" fill="none" stroke="#f59e0b" strokeWidth="4" />
      <circle cx="12" cy="12" r="4" fill="#101014" stroke="#22d3ee" strokeWidth="1" />
    </svg>
  );
}

export function LinearHalbachWorkspace({
  onHome,
  onTopologyChange,
  initialConfig,
  connectionStatus = 'online',
}: LinearHalbachWorkspaceProps) {
  const [config, setConfig] = useState<LinearHalbachArrayConfig>(
    () => structuredClone(initialConfig ?? cloneDefaultLinearHalbachConfig()),
  );
  const [stage, setStage] = useState<WorkflowStage>('design');
  const [viewportMode, setViewportMode] = useState<LinearHalbachViewportMode>('geometry');
  const [viewDimension, setViewDimension] = useState<ViewDimension>('2d');
  const [resultView, setResultView] = useState<LinearHalbachResultView>('magnitude');
  const [preview, setPreview] = useState<LinearHalbachPreview | null>(null);
  const [mesh, setMesh] = useState<LinearHalbachMeshPreview | null>(null);
  const [report, setReport] = useState<LinearHalbachReport | null>(null);
  const [selectedMagnet, setSelectedMagnet] = useState<number | null>(null);
  const [showMagnetization, setShowMagnetization] = useState(true);
  const [showProbeOverlays, setShowProbeOverlays] = useState(true);
  const [showFieldHeatmap, setShowFieldHeatmap] = useState(true);
  const [showFieldMesh, setShowFieldMesh] = useState(true);
  const [showFieldLines, setShowFieldLines] = useState(true);
  const [fieldLineDensity, setFieldLineDensity] = useState<'low' | 'medium' | 'high'>('medium');
  const [validationIssues, setValidationIssues] = useState<ValidationIssue[]>([]);
  const [progress, setProgress] = useState<HalbachSolveProgress | null>(null);
  const [busy, setBusy] = useState<'mesh' | 'solve' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [projectName, setProjectName] = useState('Linear Halbach array');
  const [projectMenuOpen, setProjectMenuOpen] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const projectMenuRef = useRef<HTMLDivElement | null>(null);
  const solveAbortRef = useRef<AbortController | null>(null);
  const localErrors = useMemo(() => collectLocalErrors(config), [config]);
  const magnetCount = 4 * config.geometry.period_count;
  const wavelength = 4 * (config.geometry.block_width + config.geometry.block_gap);
  const activeLength = magnetCount * config.geometry.block_width
    + Math.max(0, magnetCount - 1) * config.geometry.block_gap;
  const evaluatedPeriods = Math.max(
    0,
    config.geometry.period_count - 2 * config.sample_region.edge_exclusion_periods,
  );
  const magnetVolumeM3 = magnetCount
    * config.geometry.block_width
    * config.geometry.magnet_height
    * config.geometry.out_of_plane_depth
    * 1e-9;

  useEffect(() => {
    let active = true;
    const timer = window.setTimeout(() => {
      if (localErrors.length > 0) {
        setValidationIssues(localErrors);
        setPreview(null);
        return;
      }
      Promise.all([
        fetchLinearHalbachPreview(config),
        validateLinearHalbach(config),
      ])
        .then(([nextPreview, validation]) => {
          if (!active) return;
          setPreview(nextPreview);
          const response = validation as unknown as { errors?: ValidationIssue[] };
          setValidationIssues(response.errors ?? []);
          setError(null);
        })
        .catch((reason: unknown) => {
          if (!active) return;
          setError(reason instanceof Error ? reason.message : String(reason));
        });
    }, 220);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [config, localErrors]);

  useEffect(() => {
    const project: LinearHalbachProjectFile = {
      openem_schema_version: COILEM_SCHEMA_VERSION,
      project_kind: 'halbach_array',
      name: projectName,
      halbach_config: config,
    };
    window.localStorage?.setItem(
      'openem_linear_halbach_autosave',
      JSON.stringify(project),
    );
  }, [config, projectName]);

  useEffect(() => {
    if (!projectMenuOpen) return undefined;
    const closeOnOutsidePointer = (event: PointerEvent) => {
      if (projectMenuRef.current && !projectMenuRef.current.contains(event.target as Node)) {
        setProjectMenuOpen(false);
      }
    };
    document.addEventListener('pointerdown', closeOnOutsidePointer);
    return () => document.removeEventListener('pointerdown', closeOnOutsidePointer);
  }, [projectMenuOpen]);

  const changeConfig = (
    next: LinearHalbachArrayConfig,
    preserveStage = false,
  ) => {
    setConfig(next);
    setMesh(null);
    setReport(null);
    setProgress(null);
    setSelectedMagnet(null);
    if (!preserveStage) setStage('design');
    setViewportMode('geometry');
    setError(null);
  };

  const generateMesh = async () => {
    if (localErrors.length > 0) return;
    setBusy('mesh');
    setError(null);
    try {
      const generated = await fetchLinearHalbachMesh(config);
      setMesh(generated);
      setStage('solve');
      setViewportMode('mesh');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  };

  const runSolve = async () => {
    if (localErrors.length > 0) return;
    setBusy('solve');
    setError(null);
    setProgress({ stage: 'Starting Magneto2D field solve', fraction: 0, percent: 0 });
    const controller = new AbortController();
    solveAbortRef.current = controller;
    try {
      const solved = await streamLinearHalbachSolve(config, setProgress, controller.signal);
      setReport(solved);
      setStage('report');
      setViewportMode('field');
      setProgress({ stage: 'Report ready', fraction: 1, percent: 100 });
    } catch (reason) {
      if (!controller.signal.aborted) {
        setError(reason instanceof Error ? reason.message : String(reason));
      }
    } finally {
      solveAbortRef.current = null;
      setBusy(null);
    }
  };

  const saveProject = () => {
    const project: LinearHalbachProjectFile = {
      openem_schema_version: COILEM_SCHEMA_VERSION,
      project_kind: 'halbach_array',
      name: projectName,
      halbach_config: config,
    };
    const payload = JSON.stringify(project, null, 2) + '\n';
    const basename = designFileBaseName(projectName, 'linear-halbach-array').replace(/[^a-z0-9_-]+/gi, '-');
    downloadBlob(payload, `${basename}${DESIGN_FILE_EXTENSION}`, 'application/json');
  };

  const openProject = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    try {
      const raw = JSON.parse(await file.text());
      const migrated = migrateProjectFile(raw);
      const payload = migrated.data as {
        openem_schema_version?: number;
        project_kind?: string;
        name?: string;
        halbach_config?: LinearHalbachArrayConfig;
      };
      if (
        migrated.fromFuture
        || payload.project_kind !== 'halbach_array'
        || payload.halbach_config?.kind !== 'linear_halbach_array_config'
      ) {
        throw new Error('This file is not a supported linear Halbach array project.');
      }
      setProjectName(
        typeof payload.name === 'string'
          ? payload.name
          : designFileBaseName(file.name),
      );
      changeConfig(structuredClone(payload.halbach_config));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };

  const updateTopology = (topology: HalbachTopology) => {
    if (topology === 'linear') return;
    onTopologyChange(topology);
  };

  const selectedAngle = selectedMagnet == null
    ? null
    : config.array.phase_deg + selectedMagnet * (
      config.array.strong_side === 'positive_y' ? 90 : -90
    );

  const previewWarnings = (
    preview as unknown as {
      design_health?: { warnings?: ValidationIssue[] };
    } | null
  )?.design_health?.warnings ?? [];

  return (
    <div className="public-coilem-shell halbach-app" data-testid="linear-halbach-workspace">
      <header className="topbar public-coilem-topbar halbach-topbar">
        <div className="topbar-left">
          <button className="logo public-logo-button" type="button" onClick={onHome} aria-label="Return to coilEM home">
            <img className="logo-mark" src="/brand/coilem-mark.svg" alt="" aria-hidden="true" />
            <span className="logo-word">coil<span className="logo-em">EM</span><sup className="logo-stage">Beta</sup></span>
          </button>
          <div className="public-project-chip-wrap" ref={projectMenuRef}>
            <button
              className="project-chip"
              type="button"
              onClick={() => setProjectMenuOpen((open) => !open)}
              aria-haspopup="menu"
              aria-expanded={projectMenuOpen}
              aria-label="Linear Halbach design file menu"
            >
              <span className="project-save-indicator autosaved" aria-hidden="true" />
              <span className="project-name">{projectName}</span>
              <span className="caret" aria-hidden="true">▾</span>
            </button>
            {projectMenuOpen && (
              <div className="public-project-menu" role="menu" aria-label="Linear Halbach design file actions">
                <button type="button" role="menuitem" onClick={() => {
                  setProjectMenuOpen(false);
                  fileInputRef.current?.click();
                }}>
                  Open design file… ({DESIGN_FILE_EXTENSION})
                </button>
                <button type="button" role="menuitem" onClick={() => {
                  setProjectMenuOpen(false);
                  saveProject();
                }}>
                  Save design file ({DESIGN_FILE_EXTENSION})
                </button>
                <span className="menu-divider" aria-hidden="true" />
                <button type="button" role="menuitem" onClick={() => {
                  setProjectMenuOpen(false);
                  setProjectName('Linear Halbach array');
                  changeConfig(cloneDefaultLinearHalbachConfig());
                }}>
                  Reset to example design
                </button>
                <button type="button" role="menuitem" onClick={onHome}>Back to home</button>
                <span className="menu-note">Design files stay on this computer.</span>
              </div>
            )}
            <input
              ref={fileInputRef}
              type="file"
              accept={DESIGN_FILE_ACCEPT}
              hidden
              onChange={(event) => void openProject(event)}
            />
          </div>
        </div>
        <div className="topbar-workflow">
          <nav className="workflow-stepper workflow-stepper-inline" aria-label="Linear Halbach workflow">
            {(['design', 'solve', 'report'] as WorkflowStage[]).map((item, index, items) => {
              const activeIndex = items.indexOf(stage);
              const active = stage === item;
              const done = index < activeIndex;
              const disabled = (item === 'solve' && localErrors.length > 0)
                || (item === 'report' && !report);
              return (
                <span className="public-step-wrap" key={item}>
                  <button
                    type="button"
                    className={`stepper-step${active ? ' active' : ''}${done ? ' done' : ''}${disabled ? ' disabled' : ''}`}
                    disabled={disabled}
                    aria-current={active ? 'step' : undefined}
                    onClick={() => setStage(item)}
                  >
                    <span className="stepper-step-num">{done ? '\u2713' : index + 1}</span>
                    <span>{item[0].toUpperCase() + item.slice(1)}</span>
                    {active && item === 'solve' && busy === 'solve' && (
                      <span className="stepper-step-chip running">Running</span>
                    )}
                  </button>
                  {index < items.length - 1 && <span className="stepper-arrow" aria-hidden="true" />}
                </span>
              );
            })}
          </nav>
        </div>
        <div className="topbar-right">
          <div className="topbar-utility-panel">
            <span className="public-backend-select">Local backend</span>
            <span
              className={`backend-status ${connectionStatus === 'online' ? 'connected' : connectionStatus === 'checking' ? 'checking' : 'disconnected'}`}
              role="status"
            >
              <span className="status-dot" aria-hidden="true" />
              <span className="status-text">
                Local: {connectionStatus === 'online' ? 'ready' : connectionStatus === 'checking' ? 'checking' : 'not running'}
              </span>
            </span>
          </div>
        </div>
      </header>

      <main className="halbach-workspace">
        <aside
          className="halbach-config-panel"
          aria-label="Linear Halbach design parameters"
        >
          {stage === 'design' && (
            <>
              <div
                className="public-parameter-panel"
                style={{
                  width: 'auto',
                  minWidth: 0,
                  display: 'block',
                  overflow: 'visible',
                  border: 0,
                  borderRadius: 0,
                  background: 'transparent',
                  boxShadow: 'none',
                }}
              >
                <div className="param-section param-primary-section" data-guide="halbach-topology-selector">
                  <div className="param-section-label" id="halbach-topology-label">Array topology</div>
                  <div
                    className="topology-cards"
                    role="radiogroup"
                    aria-labelledby="halbach-topology-label"
                  >
                    {([
                      ['cylindrical', 'Cylindrical', 'Uniform bore field'],
                      ['linear', 'Linear', 'One-sided periodic field'],
                    ] as const).map(([topology, label, description], index) => (
                      <button
                        type="button"
                        role="radio"
                        aria-checked={topology === 'linear'}
                        className={`topo-card${topology === 'linear' ? ' active' : ''}`}
                        onClick={() => updateTopology(topology)}
                        onKeyDown={(event) => {
                          if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
                          event.preventDefault();
                          updateTopology(index === 0 ? 'linear' : 'cylindrical');
                        }}
                        key={topology}
                      >
                        <span className="topo-icon"><TopologyIcon topology={topology} /></span>
                        <span className="topo-text">
                          <span className="topo-name">{label}</span>
                          <span className="topo-sub">{description}</span>
                        </span>
                        <span className="topo-badge topo-badge-guided">2D</span>
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="halbach-panel-title">
                <span className="eyebrow">Design</span>
                <h1>Linear Halbach array</h1>
                <p>Finite array · four magnets per period · one-sided field</p>
              </div>

              <ParameterGroup title="1. Array geometry">
                <NumberInput
                  label="Magnet width"
                  suffix="mm"
                  min={0.01}
                  step={0.5}
                  value={config.geometry.block_width}
                  onChange={(value) => changeConfig(patchSection(config, 'geometry', 'block_width', value))}
                />
                <NumberInput
                  label="Magnet height"
                  suffix="mm"
                  min={0.01}
                  step={0.5}
                  value={config.geometry.magnet_height}
                  onChange={(value) => changeConfig(patchSection(config, 'geometry', 'magnet_height', value))}
                />
                <NumberInput
                  label="Out-of-plane depth"
                  suffix="mm"
                  min={0.01}
                  step={1}
                  value={config.geometry.out_of_plane_depth}
                  onChange={(value) => changeConfig(patchSection(config, 'geometry', 'out_of_plane_depth', value))}
                />
                <NumberInput
                  label="Periods"
                  min={1}
                  max={16}
                  step={1}
                  value={config.geometry.period_count}
                  onChange={(value) => changeConfig(patchSection(config, 'geometry', 'period_count', Math.round(value)))}
                />
                <NumberInput
                  label="Gap between magnets"
                  suffix="mm"
                  min={0}
                  step={0.1}
                  value={config.geometry.block_gap}
                  onChange={(value) => changeConfig(patchSection(config, 'geometry', 'block_gap', value))}
                />
                <dl className="halbach-material-summary">
                  <div><dt>Magnets</dt><dd>{magnetCount}</dd></div>
                  <div><dt>Wavelength λ</dt><dd>{formatMetric(wavelength, 'mm')}</dd></div>
                  <div><dt>Active length</dt><dd>{formatMetric(activeLength, 'mm')}</dd></div>
                </dl>
              </ParameterGroup>

              <ParameterGroup title="2. Field pattern">
                <label className="halbach-field">
                  <span>Enhanced-field side</span>
                  <select
                    value={config.array.strong_side}
                    onChange={(event) => changeConfig(patchSection(
                      config,
                      'array',
                      'strong_side',
                      event.target.value,
                    ))}
                  >
                    <option value="positive_y">Above (+Y)</option>
                    <option value="negative_y">Below (−Y)</option>
                  </select>
                </label>
                <NumberInput
                  label="Magnetization phase"
                  suffix="deg"
                  step={1}
                  value={config.array.phase_deg}
                  onChange={(value) => changeConfig(patchSection(config, 'array', 'phase_deg', value))}
                />
                <label className="halbach-check">
                  <input
                    type="checkbox"
                    checked={showMagnetization}
                    onChange={(event) => setShowMagnetization(event.target.checked)}
                  />
                  Show magnetization arrows
                </label>
              </ParameterGroup>

              <ParameterGroup title="3. Magnet material">
                <label className="halbach-field">
                  <span>Source</span>
                  <select
                    value={config.magnet.source}
                    onChange={(event) => {
                      if (event.target.value === 'catalog') {
                        changeConfig(patchMagnet(config, {
                          source: 'catalog',
                          grade: 'N42',
                          temperature_c: 20,
                        }));
                      } else {
                        const next = structuredClone(config);
                        (next as unknown as { magnet: Record<string, unknown> }).magnet = {
                          source: 'custom',
                          name: 'Custom NdFeB',
                          remanence_t: 1.3,
                          relative_permeability: 1.05,
                          temperature_c: 20,
                          reference_temperature_c: 20,
                          source_note: 'User-entered material parameters.',
                        };
                        changeConfig(next);
                      }
                    }}
                  >
                    <option value="catalog">Catalog</option>
                    <option value="custom">Custom</option>
                  </select>
                </label>
                {config.magnet.source === 'catalog' ? (
                  <>
                    <label className="halbach-field">
                      <span>Grade</span>
                      <select
                        value={config.magnet.grade}
                        onChange={(event) => changeConfig(patchMagnet(config, {
                          grade: event.target.value,
                        }))}
                      >
                        {['N35', 'N42', 'N48', 'N52', 'N48SH', 'Ferrite_Y30', 'Prius_2004_NdFeB'].map((grade) => (
                          <option key={grade}>{grade}</option>
                        ))}
                      </select>
                    </label>
                    <NumberInput
                      label="Temperature"
                      suffix="°C"
                      step={1}
                      value={config.magnet.temperature_c}
                      onChange={(value) => changeConfig(patchMagnet(config, {
                        temperature_c: value,
                      }))}
                    />
                  </>
                ) : (
                  <>
                    <label className="halbach-field">
                      <span>Material name</span>
                      <input
                        value={config.magnet.name}
                        onChange={(event) => changeConfig(patchMagnet(config, {
                          name: event.target.value,
                        }))}
                      />
                    </label>
                    <label className="halbach-field">
                      <span>Material source note</span>
                      <input
                        value={config.magnet.source_note ?? ''}
                        onChange={(event) => changeConfig(patchMagnet(config, {
                          source_note: event.target.value,
                        }))}
                      />
                    </label>
                    <NumberInput
                      label="Remanence Br"
                      suffix="T"
                      min={0.01}
                      step={0.01}
                      value={config.magnet.remanence_t}
                      onChange={(value) => changeConfig(patchMagnet(config, {
                        remanence_t: value,
                      }))}
                    />
                    <NumberInput
                      label="Relative permeability"
                      min={1}
                      step={0.01}
                      value={config.magnet.relative_permeability}
                      onChange={(value) => changeConfig(patchMagnet(config, {
                        relative_permeability: value,
                      }))}
                    />
                  </>
                )}
              </ParameterGroup>

              <ParameterGroup title="4. Evaluation lines">
                <NumberInput
                  label="Probe offset"
                  suffix="mm"
                  min={0.01}
                  step={0.5}
                  value={config.sample_region.probe_offset}
                  onChange={(value) => changeConfig(patchSection(config, 'sample_region', 'probe_offset', value))}
                />
                <NumberInput
                  label="Exclude edge periods"
                  min={0}
                  max={Math.min(7, Math.floor((config.geometry.period_count - 1) / 2))}
                  step={1}
                  value={config.sample_region.edge_exclusion_periods}
                  onChange={(value) => changeConfig(patchSection(
                    config,
                    'sample_region',
                    'edge_exclusion_periods',
                    Math.round(value),
                  ))}
                />
                <NumberInput
                  label="Samples per period"
                  min={8}
                  max={512}
                  step={8}
                  value={config.sample_region.samples_per_period}
                  onChange={(value) => {
                    const next = patchSection(
                      config,
                      'sample_region',
                      'samples_per_period',
                      Math.round(value),
                    );
                    next.solve.quality = 'custom';
                    changeConfig(next);
                  }}
                />
                <label className="halbach-check">
                  <input
                    type="checkbox"
                    checked={showProbeOverlays}
                    onChange={(event) => setShowProbeOverlays(event.target.checked)}
                  />
                  Show working and weak-side lines
                </label>
                <p className="halbach-help">
                  Metrics use {evaluatedPeriods} centered period{evaluatedPeriods === 1 ? '' : 's'}.
                  Both lines use the same offset from their nearest magnet face.
                </p>
              </ParameterGroup>

              <ParameterGroup title="5. Mesh and solve" defaultOpen={false}>
                <label className="halbach-field">
                  <span>Quality preset</span>
                  <select
                    value={config.solve.quality}
                    onChange={(event) => {
                      const quality = event.target.value as LinearHalbachArrayConfig['solve']['quality'];
                      changeConfig(
                        quality === 'custom'
                          ? patchSolve(config, 'quality', quality)
                          : withLinearHalbachQualityPreset(config, quality),
                      );
                    }}
                  >
                    <option value="quick">Quick</option>
                    <option value="standard">Standard</option>
                    <option value="fine">Fine</option>
                    <option value="custom">Custom</option>
                  </select>
                </label>
                <NumberInput
                  label="Outer padding factor"
                  min={0.5}
                  max={10}
                  step={0.5}
                  value={config.solve.mesh.outer_padding_factor}
                  onChange={(value) => changeConfig(patchMesh(config, 'outer_padding_factor', value))}
                />
                <NumberInput
                  label="Elements across magnet"
                  min={2}
                  max={40}
                  step={1}
                  value={config.solve.mesh.minimum_elements_across_magnet}
                  onChange={(value) => changeConfig(patchMesh(
                    config,
                    'minimum_elements_across_magnet',
                    Math.round(value),
                  ))}
                />
                <label className="halbach-check">
                  <input
                    type="checkbox"
                    checked={config.solve.mesh.corner_refinement}
                    onChange={(event) => changeConfig(patchMesh(
                      config,
                      'corner_refinement',
                      event.target.checked,
                    ))}
                  />
                  Refine magnet corners
                </label>
              </ParameterGroup>

              <button
                className="halbach-primary-action"
                type="button"
                disabled={localErrors.length > 0}
                onClick={() => setStage('solve')}
              >
                Continue to Solve
              </button>
            </>
          )}

          {stage === 'solve' && (
            <div className="halbach-solve-setup">
              <div className="halbach-panel-title">
                <span className="eyebrow">Analysis setup</span>
                <h2>Magneto2D</h2>
                <p>Native Gmsh mesh and linear A_z field solve.</p>
              </div>
              <label className="halbach-field">
                <span>Accuracy plan</span>
                <select
                  value={config.solve.quality}
                  disabled={busy !== null}
                  onChange={(event) => {
                    const quality = event.target.value as LinearHalbachArrayConfig['solve']['quality'];
                    changeConfig(
                      quality === 'custom'
                        ? patchSolve(config, 'quality', quality)
                        : withLinearHalbachQualityPreset(config, quality),
                      true,
                    );
                    setStage('solve');
                  }}
                >
                  <option value="quick">Quick</option>
                  <option value="standard">Standard</option>
                  <option value="fine">Fine</option>
                  <option value="custom">Custom</option>
                </select>
              </label>
              <button
                type="button"
                className="halbach-secondary-action"
                disabled={busy !== null || localErrors.length > 0}
                onClick={() => void generateMesh()}
              >
                {busy === 'mesh' ? 'Generating mesh…' : mesh ? 'Regenerate mesh preview' : 'Generate mesh preview'}
              </button>
              <button
                type="button"
                className="halbach-primary-action"
                disabled={busy !== null || localErrors.length > 0}
                onClick={() => void runSolve()}
              >
                {busy === 'solve' ? 'Solving…' : 'Run Magneto2D solve'}
              </button>
              {busy === 'solve' && (
                <button
                  type="button"
                  className="halbach-cancel-action"
                  onClick={() => solveAbortRef.current?.abort()}
                >
                  Cancel solve
                </button>
              )}
            </div>
          )}

          {stage === 'report' && (
            <div className="halbach-solve-setup">
              <div className="halbach-panel-title">
                <span className="eyebrow">Report</span>
                <h2>Results ready</h2>
                <p>Review the one-sided field metrics and solved field map.</p>
              </div>
              <button type="button" className="halbach-secondary-action" onClick={() => setStage('solve')}>
                Back to Solve
              </button>
              <button type="button" className="halbach-secondary-action" onClick={() => setStage('design')}>
                Edit Design
              </button>
            </div>
          )}
        </aside>

        <section className="halbach-stage-panel">
          <div className="halbach-viewport-shell">
            <div
              className="halbach-viewport-mode-tabs"
              role="tablist"
              aria-label="Linear Halbach visualization mode"
            >
              {([
                ['geometry', 'Geometry'],
                ['mesh', 'Mesh'],
                ['field', 'Field solution'],
              ] as Array<[LinearHalbachViewportMode, string]>).map(([mode, label]) => {
                const disabled = (mode === 'mesh' && mesh === null)
                  || (mode === 'field' && report === null);
                return (
                  <button
                    key={mode}
                    type="button"
                    role="tab"
                    aria-selected={viewportMode === mode}
                    className={viewportMode === mode ? 'is-active' : ''}
                    disabled={disabled}
                    onClick={() => setViewportMode(mode)}
                  >
                    {label}
                  </button>
                );
              })}
            </div>

            {viewportMode === 'field' && report && (
              <details className="halbach-field-layer-menu">
                <summary>Overlays</summary>
                <div
                  className="halbach-field-layer-controls"
                  role="group"
                  aria-label="Linear Halbach field solution overlays"
                >
                  <button
                    type="button"
                    aria-pressed={showFieldHeatmap}
                    onClick={() => setShowFieldHeatmap((value) => !value)}
                  ><i aria-hidden="true" />Flux density</button>
                  <button
                    type="button"
                    aria-pressed={showFieldMesh}
                    onClick={() => setShowFieldMesh((value) => !value)}
                  ><i aria-hidden="true" />Mesh</button>
                  <button
                    type="button"
                    aria-pressed={showFieldLines}
                    onClick={() => setShowFieldLines((value) => !value)}
                  ><i aria-hidden="true" />Field lines</button>
                  <button
                    type="button"
                    aria-pressed={showMagnetization}
                    onClick={() => setShowMagnetization((value) => !value)}
                  ><i aria-hidden="true" />Magnetization</button>
                  <button
                    type="button"
                    aria-pressed={showProbeOverlays}
                    onClick={() => setShowProbeOverlays((value) => !value)}
                  ><i aria-hidden="true" />Evaluation lines</button>
                  {showFieldLines && (
                    <label className="halbach-field-density-control">
                      <span>Line density</span>
                      <input
                        type="range"
                        min="0"
                        max="2"
                        step="1"
                        value={['low', 'medium', 'high'].indexOf(fieldLineDensity)}
                        aria-label="Linear Halbach field-line density"
                        aria-valuetext={fieldLineDensity}
                        onChange={(event) => {
                          const next = ['low', 'medium', 'high'][Number(event.currentTarget.value)];
                          if (next === 'low' || next === 'medium' || next === 'high') {
                            setFieldLineDensity(next);
                          }
                        }}
                      />
                      <small aria-hidden="true"><span>Low</span><span>Med</span><span>High</span></small>
                    </label>
                  )}
                </div>
              </details>
            )}

            {viewDimension === '2d' ? (
              <LinearHalbach2DViewport
                config={config}
                mesh={mesh}
                report={report}
                resultView={resultView}
                viewportMode={viewportMode}
                selectedMagnet={selectedMagnet}
                onSelectMagnet={setSelectedMagnet}
                showHeatmap={showFieldHeatmap}
                showMeshOverlay={showFieldMesh}
                showFieldLines={showFieldLines}
                fieldLineDensity={fieldLineDensity}
                showMagnetization={showMagnetization}
                showProbeOverlays={showProbeOverlays}
              />
            ) : (
              <LinearHalbach3DViewer
                config={config}
                mesh={mesh}
                report={report}
                resultView={resultView}
                viewportMode={viewportMode}
                selectedMagnet={selectedMagnet}
                onSelectMagnet={setSelectedMagnet}
                showHeatmap={showFieldHeatmap}
                showMeshOverlay={showFieldMesh}
                showFieldLines={showFieldLines}
                fieldLineDensity={fieldLineDensity}
                showMagnetization={showMagnetization}
                showProbeOverlays={showProbeOverlays}
              />
            )}

            <div className="halbach-viewport-bottom-bar">
              <div className="halbach-bottom-controls" aria-label="Linear Halbach view controls">
                <span className="halbach-control-group" role="group" aria-label="Viewport dimension">
                  <button
                    type="button"
                    className={viewDimension === '2d' ? 'is-active' : ''}
                    aria-pressed={viewDimension === '2d'}
                    onClick={() => setViewDimension('2d')}
                  >2D</button>
                  <button
                    type="button"
                    className={viewDimension === '3d' ? 'is-active' : ''}
                    aria-pressed={viewDimension === '3d'}
                    onClick={() => setViewDimension('3d')}
                  >3D</button>
                </span>
                {report && viewportMode === 'field' && (
                  <label className="halbach-result-view-control">
                    <span>Field view</span>
                    <select
                      aria-label={`Linear Halbach ${viewDimension.toUpperCase()} extruded result view`}
                      value={resultView}
                      onChange={(event) => setResultView(
                        event.target.value as LinearHalbachResultView,
                      )}
                    >
                      <option value="magnitude">|B| heatmap</option>
                      <option value="bx">B_x · along array</option>
                      <option value="by">B_y · normal</option>
                      <option value="az">A_z</option>
                      <option value="vectors">Field vectors</option>
                    </select>
                  </label>
                )}
                {viewportMode !== 'field' && (
                  <span className="halbach-control-group" role="group" aria-label="Linear 2D overlays">
                    <button
                      type="button"
                      className={showMagnetization ? 'is-active' : ''}
                      aria-pressed={showMagnetization}
                      onClick={() => setShowMagnetization((value) => !value)}
                    >
                      Magnetization
                    </button>
                    <button
                      type="button"
                      className={showProbeOverlays ? 'is-active' : ''}
                      aria-pressed={showProbeOverlays}
                      onClick={() => setShowProbeOverlays((value) => !value)}
                    >
                      Evaluation lines
                    </button>
                  </span>
                )}
              </div>
              <div className="halbach-viewport-status" aria-live="polite">
                {selectedMagnet == null ? (
                  <span>{magnetCount} magnets · {config.geometry.period_count} periods</span>
                ) : (
                  <>
                    <span>
                      Magnet {selectedMagnet + 1} · period {Math.floor(selectedMagnet / 4) + 1}
                      {' · '}α {formatMetric(selectedAngle, 'deg')}
                    </span>
                    <button type="button" onClick={() => setSelectedMagnet(null)} aria-label="Clear magnet selection">×</button>
                  </>
                )}
              </div>
            </div>
          </div>
        </section>

        <aside className="halbach-run-panel" aria-label="Linear design health and solve information">
          {stage === 'design' && (
            <>
              <div className="halbach-panel-title">
                <span className="eyebrow">Design health</span>
              </div>
              <div className={`halbach-ready-card ${localErrors.length === 0 ? 'ready' : 'blocked'}`}>
                <span aria-hidden="true">{localErrors.length === 0 ? '✓' : '!'}</span>
                <div>
                  <strong>{localErrors.length === 0 ? 'Ready to solve' : 'Needs attention'}</strong>
                  <small>
                    {localErrors.length === 0
                      ? `${magnetCount} magnets · ${evaluatedPeriods} evaluated period${evaluatedPeriods === 1 ? '' : 's'}`
                      : `${localErrors.length} blocking issue(s)`}
                  </small>
                </div>
              </div>
              {localErrors.map((issue) => (
                <div key={`${issue.field}-${issue.message}`} className="halbach-issue error">
                  <strong>{issue.field}</strong><span>{issue.message}</span>
                </div>
              ))}
              {validationIssues
                .filter((issue) => !localErrors.some((local) => local.field === issue.field))
                .map((issue) => (
                  <div key={`${issue.field}-${issue.message}`} className="halbach-issue error">
                    <strong>{issue.field}</strong><span>{issue.message}</span>
                  </div>
                ))}
              {previewWarnings.map((issue) => (
                <div key={`${issue.code}-${issue.field}`} className="halbach-issue warning">
                  <strong>{issue.code?.replace(/_/g, ' ') ?? issue.field}</strong>
                  <span>{issue.message}</span>
                </div>
              ))}
              <dl className="halbach-health-grid">
                <div><dt>Wavelength λ</dt><dd>{formatMetric(wavelength, 'mm')}</dd></div>
                <div><dt>Active length</dt><dd>{formatMetric(activeLength, 'mm')}</dd></div>
                <div><dt>Height / λ</dt><dd>{formatMetric(config.geometry.magnet_height / wavelength)}</dd></div>
                <div><dt>Probe offset / λ</dt><dd>{formatMetric(config.sample_region.probe_offset / wavelength)}</dd></div>
                <div><dt>Evaluated periods</dt><dd>{evaluatedPeriods}</dd></div>
                <div><dt>Magnet volume</dt><dd>{formatMetric(magnetVolumeM3 * 1e6, 'cm³')}</dd></div>
              </dl>
            </>
          )}

          {stage === 'solve' && (
            <>
              <div className="halbach-panel-title">
                <span className="eyebrow">Solve</span>
                <h2>Magneto2D</h2>
                <p>Linear A_z field · {config.solve.quality} preset</p>
              </div>
              <div className="halbach-output-list">
                <span>✓ Field map and A_z contours</span>
                <span>✓ Working-line field statistics</span>
                <span>✓ Weak-side suppression</span>
                <span>✓ Demagnetization screening</span>
              </div>
              {mesh && (
                <dl className="halbach-mesh-summary">
                  <div><dt>Nodes</dt><dd>{formatMetric(Number(mesh.mesh_info.node_count ?? mesh.nodes_mm.length), '', 7)}</dd></div>
                  <div><dt>Triangles</dt><dd>{formatMetric(Number(mesh.mesh_info.element_count ?? mesh.triangles.length), '', 7)}</dd></div>
                  <div><dt>Corner refinement</dt><dd>{mesh.mesh_info.corner_refinement === true ? 'Applied' : 'Off'}</dd></div>
                  <div><dt>Problem hash</dt><dd title={mesh.magnetostatic_problem_sha256}>{mesh.magnetostatic_problem_sha256.slice(0, 12)}…</dd></div>
                </dl>
              )}
              {busy === 'solve' && (
                <>
                  <progress max={100} value={progress?.percent ?? 0}>{progress?.percent ?? 0}%</progress>
                  <p className="halbach-progress" aria-live="polite">
                    {progress?.stage} · {formatMetric(progress?.percent, '%')}
                  </p>
                </>
              )}
              <div className="halbach-fidelity-card">{LINEAR_HALBACH_MODEL_NOTICE}</div>
            </>
          )}

          {stage === 'report' && report && (
            <>
              <div className="halbach-panel-title">
                <span className="eyebrow">Report</span>
                <h2>One-sided field solution</h2>
                <p>Finite linear array with centered evaluation lines</p>
              </div>
              <dl className="halbach-report-metrics">
                <div className="hero">
                  <dt>Working-line RMS |B|</dt>
                  <dd>{formatMetric(reportNumber(
                    report,
                    ['working_field', 'b_magnitude_t', 'rms'],
                  ), 'T', 6)}</dd>
                </div>
                <div><dt>Working mean |B|</dt><dd>{formatMetric(reportNumber(
                  report,
                  ['working_field', 'b_magnitude_t', 'mean'],
                ), 'T')}</dd></div>
                <div><dt>Working peak |B|</dt><dd>{formatMetric(reportNumber(
                  report,
                  ['working_field', 'b_magnitude_t', 'maximum'],
                ), 'T')}</dd></div>
                <div><dt>Working-line ripple</dt><dd>{formatMetric(reportNumber(
                  report,
                  ['working_field', 'ripple_ppm'],
                ), 'ppm')}</dd></div>
                <div><dt>Weak-side RMS |B|</dt><dd>{formatMetric(reportNumber(
                  report,
                  ['leakage_field', 'b_magnitude_t', 'rms'],
                ), 'T')}</dd></div>
                <div><dt>Leakage ratio</dt><dd>{formatMetric(reportNumber(
                  report,
                  ['one_sidedness', 'leakage_ratio_rms'],
                ))}</dd></div>
                <div><dt>Suppression ratio</dt><dd>{formatMetric(reportNumber(
                  report,
                  ['one_sidedness', 'suppression_ratio'],
                ))}</dd></div>
                <div><dt>Magnet volume</dt><dd>{formatMetric(reportNumber(
                  report,
                  ['magnet', 'volume_m3'],
                ) === null ? null : (reportNumber(report, ['magnet', 'volume_m3']) ?? 0) * 1e6, 'cm³')}</dd></div>
                <div><dt>Magnet mass</dt><dd>{formatMetric(reportNumber(
                  report,
                  ['magnet', 'mass_kg'],
                ), 'kg')}</dd></div>
              </dl>
              <details className="halbach-report-details">
                <summary>Timing and provenance</summary>
                {Object.entries(
                  (report as unknown as { timings_ms?: Record<string, number> }).timings_ms ?? {},
                ).map(([label, value]) => (
                  <div key={label}><span>{label.replace(/_/g, ' ')}</span><strong>{formatMetric(value, 'ms')}</strong></div>
                ))}
                <div><span>Working-line samples</span><strong>{formatMetric(reportNumber(
                  report,
                  ['working_field', 'sample_count'],
                ))}</strong></div>
              </details>
              <div className="halbach-fidelity-card">{LINEAR_HALBACH_MODEL_NOTICE}</div>
            </>
          )}

          {error && <div className="halbach-error-banner" role="alert">{error}</div>}
        </aside>
      </main>
    </div>
  );
}
