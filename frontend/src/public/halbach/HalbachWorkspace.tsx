import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type ReactNode,
} from 'react';

import {
  downloadHalbachExport,
  fetchHalbachMesh,
  fetchHalbachPreview,
  streamHalbachSolve,
  validateHalbach,
  type HalbachExportKind,
} from './api';
import { migrateProjectFile, COILEM_SCHEMA_VERSION } from '../../api/projectSchema';
import { DESIGN_FILE_ACCEPT, DESIGN_FILE_EXTENSION, designFileBaseName } from '../designFile';
import { Halbach2DViewport } from './Halbach2DViewport';
import { Halbach3DViewer } from './Halbach3DViewer';
import { LinearHalbachWorkspace } from './LinearHalbachWorkspace';
import { halbachMagnetizationAngleDeg } from './geometry';
import {
  cloneDefaultHalbachConfig,
  HALBACH_AXIAL_NOTICE,
  type HalbachArrayConfig,
  type HalbachCatalogMagnet,
  type HalbachDesignHealth,
  type HalbachMeshPreview,
  type HalbachPreview,
  type HalbachProjectFile,
  type HalbachReport,
  type HalbachResultView,
  type HalbachSolveProgress,
  type HalbachValidationIssue,
  type HalbachViewportMode,
  type LinearHalbachArrayConfig,
  withHalbachQualityPreset,
} from './types';
import './halbach.css';

type WorkflowStage = 'design' | 'solve' | 'report';
type ViewDimension = '2d' | '3d';
type HalbachTopology = 'cylindrical' | 'linear';

interface HalbachWorkspaceProps {
  onHome: () => void;
  initialConfig?: HalbachArrayConfig | LinearHalbachArrayConfig;
  connectionStatus?: 'checking' | 'online' | 'offline';
}

interface CylindricalHalbachWorkspaceProps {
  onHome: () => void;
  onTopologyChange: (topology: HalbachTopology) => void;
  initialConfig?: HalbachArrayConfig;
  connectionStatus?: 'checking' | 'online' | 'offline';
}

interface NumberInputProps {
  label: string;
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
  suffix?: string;
}

function NumberInput({
  label,
  value,
  onChange,
  min,
  max,
  step = 1,
  suffix,
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

function formatMetric(value: number | null | undefined, unit = '', digits = 4): string {
  if (value == null || !Number.isFinite(value)) return 'Unavailable';
  return `${value.toLocaleString(undefined, { maximumSignificantDigits: digits })}${unit ? ` ${unit}` : ''}`;
}

function collectLocalErrors(config: HalbachArrayConfig): HalbachValidationIssue[] {
  const errors: HalbachValidationIssue[] = [];
  const add = (field: string, message: string) => errors.push({ field, message });
  if (!(config.geometry.inner_radius > 0)) add('geometry.inner_radius', 'Inner radius must be greater than zero.');
  if (!(config.geometry.outer_radius > config.geometry.inner_radius)) {
    add('geometry.outer_radius', 'Outer radius must exceed the inner radius.');
  }
  if (!(config.geometry.axial_length > 0)) add('geometry.axial_length', 'Axial length must be greater than zero.');
  if (!Number.isInteger(config.geometry.segment_count) || config.geometry.segment_count < 4 || config.geometry.segment_count > 64) {
    add('geometry.segment_count', 'Segment count must be an integer from 4 through 64.');
  }
  const pitch = 360 / Math.max(1, config.geometry.segment_count);
  if (config.geometry.segment_gap_angle < 0 || config.geometry.segment_gap_angle >= pitch / 2) {
    add('geometry.segment_gap_angle', 'Segment gap must be non-negative and less than half the pitch.');
  }
  if (!(config.sample_region.radius > 0 && config.sample_region.radius < 0.95 * config.geometry.inner_radius)) {
    add('sample_region.radius', 'ROI radius must be positive and below 95% of the bore radius.');
  }
  const boundary = config.geometry.outer_radius * config.solve.mesh.outer_boundary_radius_factor;
  if (!(config.sample_region.leakage_probe_radius > config.geometry.outer_radius
    && config.sample_region.leakage_probe_radius < boundary)) {
    add('sample_region.leakage_probe_radius', 'Leakage radius must lie between the magnet OD and outer boundary.');
  }
  return errors;
}

function designFile(config: HalbachArrayConfig, name: string): HalbachProjectFile {
  return {
    openem_schema_version: COILEM_SCHEMA_VERSION,
    project_kind: 'halbach_array',
    name,
    halbach_config: config,
  };
}

function downloadBlob(body: BlobPart, filename: string, type: string): void {
  const url = URL.createObjectURL(new Blob([body], { type }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function CylindricalHalbachWorkspace({
  onHome,
  onTopologyChange,
  initialConfig,
  connectionStatus = 'online',
}: CylindricalHalbachWorkspaceProps) {
  const [config, setConfig] = useState<HalbachArrayConfig>(
    () => structuredClone(initialConfig ?? cloneDefaultHalbachConfig()),
  );
  const [stage, setStage] = useState<WorkflowStage>('design');
  const [dimension, setDimension] = useState<ViewDimension>('2d');
  const [resultView, setResultView] = useState<HalbachResultView>('magnitude');
  const [viewportMode, setViewportMode] = useState<HalbachViewportMode>('geometry');
  const [preview, setPreview] = useState<HalbachPreview | null>(null);
  const [mesh, setMesh] = useState<HalbachMeshPreview | null>(null);
  const [report, setReport] = useState<HalbachReport | null>(null);
  const [axialOutputsStale, setAxialOutputsStale] = useState(false);
  const [selectedSegment, setSelectedSegment] = useState<number | null>(null);
  const [showMagnetization, setShowMagnetization] = useState(true);
  const [showSamplingOverlays, setShowSamplingOverlays] = useState(true);
  const [showFieldHeatmap, setShowFieldHeatmap] = useState(true);
  const [showFieldMesh, setShowFieldMesh] = useState(true);
  const [showFieldLines, setShowFieldLines] = useState(true);
  const [fieldLineDensity, setFieldLineDensity] = useState<'low' | 'medium' | 'high'>('medium');
  const [validationIssues, setValidationIssues] = useState<HalbachValidationIssue[]>([]);
  const [progress, setProgress] = useState<HalbachSolveProgress | null>(null);
  const [busy, setBusy] = useState<'mesh' | 'solve' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [projectName, setProjectName] = useState('Cylindrical Halbach array');
  const [projectMenuOpen, setProjectMenuOpen] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const projectMenuRef = useRef<HTMLDivElement | null>(null);
  const solveAbortRef = useRef<AbortController | null>(null);
  const localErrors = useMemo(() => collectLocalErrors(config), [config]);
  const health: HalbachDesignHealth | null = preview?.design_health ?? null;
  const fieldViewConfig = useMemo(
    () => (
      axialOutputsStale && report !== null
        ? {
            ...config,
            geometry: {
              ...config.geometry,
              axial_length: report.configuration.geometry.axial_length,
            },
          }
        : config
    ),
    [axialOutputsStale, config, report],
  );

  useEffect(() => {
    let active = true;
    const timer = window.setTimeout(() => {
      if (localErrors.length > 0) {
        setValidationIssues(localErrors);
        setPreview(null);
        return;
      }
      Promise.all([fetchHalbachPreview(config), validateHalbach(config)])
        .then(([nextPreview, validation]) => {
          if (!active) return;
          setPreview(nextPreview);
          setValidationIssues(validation.errors);
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
    window.localStorage?.setItem(
      'openem_halbach_autosave',
      JSON.stringify(designFile(config, projectName)),
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

  const changeConfig = (next: HalbachArrayConfig, preserveField = false) => {
    setConfig(next);
    setMesh(null);
    if (preserveField && report !== null) {
      setAxialOutputsStale(true);
      setViewportMode('field');
    } else if (!preserveField) {
      if (report !== null) setStage('design');
      setReport(null);
      setAxialOutputsStale(false);
      setViewportMode('geometry');
    }
    setError(null);
  };

  const changeGeometry = <K extends keyof HalbachArrayConfig['geometry']>(
    key: K,
    value: HalbachArrayConfig['geometry'][K],
  ) => {
    changeConfig(
      { ...config, geometry: { ...config.geometry, [key]: value } },
      key === 'axial_length',
    );
  };

  const changeSample = <K extends keyof HalbachArrayConfig['sample_region']>(
    key: K,
    value: HalbachArrayConfig['sample_region'][K],
  ) => {
    changeConfig({ ...config, sample_region: { ...config.sample_region, [key]: value } });
  };

  const generateMesh = async () => {
    if (localErrors.length > 0) return;
    setBusy('mesh');
    setError(null);
    try {
      const generated = await fetchHalbachMesh(config);
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
      const solved = await streamHalbachSolve(config, setProgress, controller.signal);
      setReport(solved);
      setAxialOutputsStale(false);
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
    const payload = JSON.stringify(designFile(config, projectName), null, 2) + '\n';
    const basename = designFileBaseName(projectName, 'halbach-array').replace(/[^a-z0-9_-]+/gi, '-');
    downloadBlob(payload, `${basename}${DESIGN_FILE_EXTENSION}`, 'application/json');
  };

  const openProject = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    try {
      const raw = JSON.parse(await file.text());
      const migrated = migrateProjectFile(raw);
      const payload = migrated.data as Partial<HalbachProjectFile>;
      if (
        migrated.fromFuture
        || payload.project_kind !== 'halbach_array'
        || payload.halbach_config?.kind !== 'halbach_array_config'
      ) {
        throw new Error(
          payload.project_kind == null
            ? 'This is a motor project (an absent project_kind means motor), not a Halbach project.'
            : 'This file is not a supported Halbach array project.',
        );
      }
      setProjectName(typeof payload.name === 'string' ? payload.name : designFileBaseName(file.name));
      changeConfig(structuredClone(payload.halbach_config));
      setStage('design');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };

  const exportResult = async (kind: HalbachExportKind) => {
    if (!report) return;
    setError(null);
    try {
      await downloadHalbachExport(kind, report);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };

  const magnetSummary = preview?.material ?? null;
  const selectedSegmentAngle = selectedSegment == null
    ? null
    : config.geometry.segment_start_angle + (selectedSegment + 0.5) * 360 / config.geometry.segment_count;

  return (
    <div className="public-coilem-shell halbach-app" data-testid="halbach-workspace">
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
              aria-label="Halbach design file menu"
            >
              <span className="project-save-indicator autosaved" aria-hidden="true" />
              <span className="project-name">{projectName}</span>
              <span className="caret" aria-hidden="true">▾</span>
            </button>
            {projectMenuOpen && (
              <div className="public-project-menu" role="menu" aria-label="Halbach design file actions">
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
                  setProjectName('Cylindrical Halbach array');
                  changeConfig(cloneDefaultHalbachConfig());
                  setStage('design');
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
          <nav className="workflow-stepper workflow-stepper-inline" aria-label="Halbach workflow">
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
            <span className={`backend-status ${connectionStatus === 'online' ? 'connected' : connectionStatus === 'checking' ? 'checking' : 'disconnected'}`} role="status">
              <span className="status-dot" aria-hidden="true" />
              <span className="status-text">Local: {connectionStatus === 'online' ? 'ready' : connectionStatus === 'checking' ? 'checking' : 'not running'}</span>
            </span>
          </div>
        </div>
      </header>

      <div className="halbach-model-notice" role="note">{HALBACH_AXIAL_NOTICE}</div>

      <main className="halbach-workspace">
        <aside className="halbach-config-panel" aria-label="Halbach design parameters">
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
                  <div className="topology-cards" role="radiogroup" aria-labelledby="halbach-topology-label">
                    <button
                      type="button"
                      role="radio"
                      aria-checked="true"
                      className="topo-card active"
                      onClick={() => onTopologyChange('cylindrical')}
                      onKeyDown={(event) => {
                        if (event.key === 'ArrowRight') {
                          event.preventDefault();
                          onTopologyChange('linear');
                        }
                      }}
                    >
                      <span className="topo-icon" aria-hidden="true">
                        <svg viewBox="0 0 24 24" width="22" height="22">
                          <circle cx="12" cy="12" r="9" fill="none" stroke="#f59e0b" strokeWidth="4" />
                          <circle cx="12" cy="12" r="4" fill="#101014" stroke="#22d3ee" strokeWidth="1" />
                        </svg>
                      </span>
                      <span className="topo-text"><span className="topo-name">Cylindrical</span><span className="topo-sub">Uniform bore field</span></span>
                      <span className="topo-badge topo-badge-guided">2D</span>
                    </button>
                    <button
                      type="button"
                      role="radio"
                      aria-checked="false"
                      className="topo-card"
                      onClick={() => onTopologyChange('linear')}
                      onKeyDown={(event) => {
                        if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
                          event.preventDefault();
                          onTopologyChange('cylindrical');
                        }
                      }}
                    >
                      <span className="topo-icon" aria-hidden="true">
                        <svg viewBox="0 0 28 20" width="24" height="20">
                          {[0, 1, 2, 3].map((index) => (
                            <rect key={index} x={1 + 6.7 * index} y="6" width="5.5" height="9" rx="1" fill={index % 2 === 0 ? '#f59e0b' : '#22d3ee'} />
                          ))}
                          <path d="M3 3h21" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                        </svg>
                      </span>
                      <span className="topo-text"><span className="topo-name">Linear</span><span className="topo-sub">One-sided periodic field</span></span>
                      <span className="topo-badge topo-badge-guided">2D</span>
                    </button>
                  </div>
                </div>
              </div>
              <div className="halbach-panel-title">
                <span className="eyebrow">Design</span>
                <h1>Cylindrical Halbach array</h1>
                <p>Internal-field p = 1 · full 360° planar solve</p>
              </div>
          <ParameterGroup title="1. Cylinder geometry">
            <NumberInput
              label="Bore diameter"
              suffix="mm"
              min={0.02}
              step={1}
              value={2 * config.geometry.inner_radius}
              onChange={(value) => changeGeometry('inner_radius', value / 2)}
            />
            <NumberInput
              label="Outer diameter"
              suffix="mm"
              min={0.04}
              step={1}
              value={2 * config.geometry.outer_radius}
              onChange={(value) => changeGeometry('outer_radius', value / 2)}
            />
            <NumberInput
              label="Axial length"
              suffix="mm"
              min={0.01}
              value={config.geometry.axial_length}
              onChange={(value) => changeGeometry('axial_length', value)}
            />
            <NumberInput
              label="Segments"
              min={4}
              max={64}
              value={config.geometry.segment_count}
              onChange={(value) => changeGeometry('segment_count', Math.round(value))}
            />
            <NumberInput
              label="Gap per segment"
              suffix="deg"
              min={0}
              step={0.05}
              value={config.geometry.segment_gap_angle}
              onChange={(value) => changeGeometry('segment_gap_angle', value)}
            />
            <NumberInput
              label="Seam rotation"
              suffix="deg"
              step={1}
              value={config.geometry.segment_start_angle}
              onChange={(value) => changeGeometry('segment_start_angle', value)}
            />
          </ParameterGroup>

          <ParameterGroup title="2. Field pattern">
            <label className="halbach-field">
              <span>Field mode</span>
              <select value="internal" disabled aria-label="Field mode"><option>Internal dipole (p = 1)</option></select>
            </label>
            <NumberInput
              label="Requested direction"
              suffix="deg CCW"
              step={1}
              value={config.array.field_direction}
              onChange={(value) => changeConfig({
                ...config,
                array: { ...config.array, field_direction: value },
              })}
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
                    changeConfig({ ...config, magnet: { source: 'catalog', grade: 'N42', temperature_c: 20 } });
                  } else {
                    changeConfig({
                      ...config,
                      magnet: {
                        source: 'custom',
                        name: 'Custom NdFeB',
                        remanence_t: 1.3,
                        relative_permeability: 1.05,
                        temperature_c: 20,
                        reference_temperature_c: 20,
                        source_note: 'User-entered material parameters.',
                      },
                    });
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
                    onChange={(event) => {
                      const magnet = config.magnet;
                      if (magnet.source === 'catalog') {
                        changeConfig({
                          ...config,
                          magnet: {
                            ...magnet,
                            grade: event.target.value as HalbachCatalogMagnet['grade'],
                          },
                        });
                      }
                    }}
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
                  onChange={(value) => {
                    if (config.magnet.source === 'catalog') {
                      changeConfig({ ...config, magnet: { ...config.magnet, temperature_c: value } });
                    }
                  }}
                />
              </>
            ) : (
              <>
                <label className="halbach-field">
                  <span>Material name</span>
                  <input
                    value={config.magnet.name}
                    onChange={(event) => {
                      if (config.magnet.source === 'custom') {
                        changeConfig({ ...config, magnet: { ...config.magnet, name: event.target.value } });
                      }
                    }}
                  />
                </label>
                <label className="halbach-field">
                  <span>Material source note</span>
                  <input
                    value={config.magnet.source_note ?? ''}
                    onChange={(event) => {
                      if (config.magnet.source === 'custom') {
                        changeConfig({
                          ...config,
                          magnet: { ...config.magnet, source_note: event.target.value },
                        });
                      }
                    }}
                  />
                </label>
                <NumberInput
                  label="Remanence Br"
                  suffix="T"
                  step={0.01}
                  value={config.magnet.remanence_t}
                  onChange={(value) => {
                    if (config.magnet.source === 'custom') {
                      changeConfig({ ...config, magnet: { ...config.magnet, remanence_t: value } });
                    }
                  }}
                />
                <NumberInput
                  label="Relative permeability"
                  step={0.01}
                  min={1}
                  value={config.magnet.relative_permeability}
                  onChange={(value) => {
                    if (config.magnet.source === 'custom') {
                      changeConfig({ ...config, magnet: { ...config.magnet, relative_permeability: value } });
                    }
                  }}
                />
                <NumberInput
                  label="Intrinsic Hcj"
                  suffix="A/m"
                  min={0}
                  step={1000}
                  value={config.magnet.intrinsic_coercivity_a_per_m ?? 0}
                  onChange={(value) => {
                    if (config.magnet.source === 'custom') {
                      changeConfig({
                        ...config,
                        magnet: {
                          ...config.magnet,
                          intrinsic_coercivity_a_per_m: value > 0 ? value : undefined,
                        },
                      });
                    }
                  }}
                />
                <NumberInput
                  label="Density"
                  suffix="kg/m³"
                  min={0}
                  step={10}
                  value={config.magnet.density_kg_per_m3 ?? 0}
                  onChange={(value) => {
                    if (config.magnet.source === 'custom') {
                      changeConfig({
                        ...config,
                        magnet: { ...config.magnet, density_kg_per_m3: value > 0 ? value : undefined },
                      });
                    }
                  }}
                />
              </>
            )}
            {magnetSummary && (
              <dl className="halbach-material-summary">
                <div><dt>Resolved Br</dt><dd>{formatMetric(Number(magnetSummary.remanence_t), 'T')}</dd></div>
                <div><dt>μr</dt><dd>{formatMetric(Number(magnetSummary.relative_permeability))}</dd></div>
                <div><dt>Hcj status</dt><dd>{String(magnetSummary.coercivity_classification ?? 'unknown')}</dd></div>
                <div><dt>Density</dt><dd>{formatMetric(magnetSummary.density_kg_per_m3 as number | null, 'kg/m³')}</dd></div>
              </dl>
            )}
          </ParameterGroup>

          <ParameterGroup title="4. Sample region">
            <NumberInput
              label="Bore ROI radius"
              suffix="mm"
              min={0.01}
              step={0.5}
              value={config.sample_region.radius}
              onChange={(value) => changeSample('radius', value)}
            />
            <NumberInput
              label="Leakage probe radius"
              suffix="mm"
              min={0.01}
              step={1}
              value={config.sample_region.leakage_probe_radius}
              onChange={(value) => changeSample('leakage_probe_radius', value)}
            />
            <label className="halbach-check">
              <input
                type="checkbox"
                checked={showSamplingOverlays}
                onChange={(event) => setShowSamplingOverlays(event.target.checked)}
              />
              Show ROI and leakage overlays
            </label>
          </ParameterGroup>

          <ParameterGroup title="5. Advanced geometry" defaultOpen={false}>
            <p className="halbach-help">
              V1 is fixed to a full 360° internal dipole using annular-wedge magnets.
              Higher multipoles, yokes, coils, and 3D field solves are intentionally unavailable.
            </p>
            <label className="halbach-field">
              <span>Quality preset</span>
              <select
                value={config.solve.quality}
                onChange={(event) => {
                  const quality = event.target.value as HalbachArrayConfig['solve']['quality'];
                  changeConfig(
                    quality === 'custom'
                      ? { ...config, solve: { ...config.solve, quality } }
                      : withHalbachQualityPreset(config, quality),
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
              label="Outer boundary factor"
              min={2}
              max={12}
              step={0.5}
              value={config.solve.mesh.outer_boundary_radius_factor}
              onChange={(value) => changeConfig({
                ...config,
                solve: {
                  ...config.solve,
                  quality: 'custom',
                  mesh: { ...config.solve.mesh, outer_boundary_radius_factor: value },
                },
              })}
            />
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
                    const quality = event.target.value as HalbachArrayConfig['solve']['quality'];
                    changeConfig(
                      quality === 'custom'
                        ? { ...config, solve: { ...config.solve, quality } }
                        : withHalbachQualityPreset(config, quality),
                    );
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
                <button type="button" className="halbach-cancel-action" onClick={() => solveAbortRef.current?.abort()}>
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
                <p>Review outputs on the right or return to the analysis setup.</p>
              </div>
              <NumberInput
                label="Axial length"
                suffix="mm"
                min={0.01}
                value={config.geometry.axial_length}
                onChange={(value) => changeGeometry('axial_length', value)}
              />
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
              aria-label="Halbach visualization mode"
            >
              {([
                ['geometry', 'Geometry'],
                ['mesh', 'Mesh'],
                ['field', 'Field solution'],
              ] as Array<[HalbachViewportMode, string]>).map(([mode, label]) => {
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
                    onClick={() => {
                      setViewportMode(mode);
                      if (mode !== 'geometry') setDimension('2d');
                    }}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
            {dimension === '2d' && viewportMode === 'field' && report && (
              <details className="halbach-field-layer-menu">
                <summary>Overlays</summary>
                <div
                  className="halbach-field-layer-controls"
                  role="group"
                  aria-label="Halbach field solution overlays"
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
                    aria-pressed={showSamplingOverlays}
                    onClick={() => setShowSamplingOverlays((value) => !value)}
                  ><i aria-hidden="true" />ROI + leakage</button>
                  {showFieldLines && (
                    <label className="halbach-field-density-control">
                      <span>Line density</span>
                      <input
                        type="range"
                        min="0"
                        max="2"
                        step="1"
                        value={['low', 'medium', 'high'].indexOf(fieldLineDensity)}
                        aria-label="Halbach field-line density"
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
            {dimension === '2d' ? (
              <Halbach2DViewport
                config={config}
                mesh={mesh}
                report={report}
                resultView={resultView}
                viewportMode={viewportMode}
                selectedSegment={selectedSegment}
                onSelectSegment={setSelectedSegment}
                showHeatmap={showFieldHeatmap}
                showMeshOverlay={showFieldMesh}
                showFieldLines={showFieldLines}
                fieldLineDensity={fieldLineDensity}
                showMagnetization={showMagnetization}
                showSamplingOverlays={showSamplingOverlays}
              />
            ) : (
              <Halbach3DViewer
                config={fieldViewConfig}
                report={report}
                axialOutputsStale={axialOutputsStale}
                selectedSegment={selectedSegment}
                onSelectSegment={setSelectedSegment}
              />
            )}
            <div className="halbach-viewport-bottom-bar">
              <div className="halbach-bottom-controls" aria-label="Halbach view and overlay controls">
                <span className="halbach-control-group" role="tablist" aria-label="Viewport dimension">
                  <button
                    type="button"
                    role="tab"
                    aria-selected={dimension === '2d'}
                    className={dimension === '2d' ? 'is-active' : ''}
                    onClick={() => setDimension('2d')}
                  >2D</button>
                  <button
                    type="button"
                    role="tab"
                    aria-selected={dimension === '3d'}
                    className={dimension === '3d' ? 'is-active' : ''}
                    onClick={() => {
                      setDimension('3d');
                      setViewportMode('geometry');
                    }}
                  >3D</button>
                </span>
                {report && dimension === '2d' && viewportMode === 'field' && (
                  <label className="halbach-result-view-control">
                    <span>Field view</span>
                    <select
                      aria-label="2D result view"
                      value={resultView}
                      onChange={(event) => setResultView(event.target.value as HalbachResultView)}
                    >
                      <option value="magnitude">|B| heatmap</option>
                      <option value="parallel">B parallel</option>
                      <option value="perpendicular">B perpendicular</option>
                      <option value="az">A_z</option>
                      <option value="vectors">Field vectors</option>
                    </select>
                  </label>
                )}
                {dimension === '2d' && viewportMode !== 'field' && (
                  <span className="halbach-control-group" role="group" aria-label="2D overlays">
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
                      className={showSamplingOverlays ? 'is-active' : ''}
                      aria-pressed={showSamplingOverlays}
                      onClick={() => setShowSamplingOverlays((value) => !value)}
                    >
                      ROI + leakage
                    </button>
                  </span>
                )}
              </div>
              <div className="halbach-viewport-status" aria-live="polite">
                {selectedSegment == null ? (
                  <span>{config.geometry.segment_count} segments</span>
                ) : (
                  <>
                    <span>
                      Segment {selectedSegment + 1} · theta {formatMetric(selectedSegmentAngle, 'deg')}
                      {' · '}alpha {formatMetric(
                        selectedSegmentAngle == null
                          ? null
                          : halbachMagnetizationAngleDeg(
                            selectedSegmentAngle,
                            config.array.field_direction,
                          ),
                        'deg',
                      )}
                    </span>
                    <button type="button" onClick={() => setSelectedSegment(null)} aria-label="Clear segment selection">×</button>
                  </>
                )}
              </div>
            </div>
          </div>
        </section>

        <aside className="halbach-run-panel" aria-label="Design health and solve controls">
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
                      ? `${health?.checks.length ?? 0} checks passed · ${(health?.warnings.length ?? 0)} notices`
                      : `${localErrors.length} blocking issue(s)`}
                  </small>
                </div>
              </div>
              {localErrors.map((issue) => (
                <div key={`${issue.field}-${issue.message}`} className="halbach-issue error">
                  <strong>{issue.field}</strong><span>{issue.message}</span>
                </div>
              ))}
              {(health?.warnings ?? []).map((issue) => (
                <div key={`${issue.code}-${issue.field}`} className="halbach-issue warning">
                  <strong>{issue.code?.replace(/_/g, ' ')}</strong><span>{issue.message}</span>
                </div>
              ))}
              {health && (
                <dl className="halbach-health-grid">
                  <div><dt>rₒ / rᵢ</dt><dd>{formatMetric(config.geometry.outer_radius / config.geometry.inner_radius)}</dd></div>
                  <div><dt>Length / OD</dt><dd>{formatMetric(config.geometry.axial_length / (2 * config.geometry.outer_radius))}</dd></div>
                  <div><dt>Coverage</dt><dd>{formatMetric(100 * (1 - config.geometry.segment_gap_angle / (360 / config.geometry.segment_count)), '%')}</dd></div>
                  <div><dt>ROI / bore</dt><dd>{formatMetric(100 * config.sample_region.radius / config.geometry.inner_radius, '%')}</dd></div>
                  <div><dt>Segmented estimate</dt><dd>{formatMetric(health.analytics.segmented_bore_field_estimate_t, 'T')}</dd></div>
                  <div><dt>Magnet volume</dt><dd>{formatMetric(health.analytics.magnet_volume_m3 * 1e6, 'cm³')}</dd></div>
                </dl>
              )}
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
                <span>✓ Bore statistics and direction</span>
                <span>✓ External leakage</span>
                <span>✓ Demagnetization screening</span>
              </div>
              {mesh && (
                <dl className="halbach-mesh-summary">
                  <div><dt>Nodes</dt><dd>{formatMetric(Number(mesh.mesh_info.node_count ?? mesh.nodes_mm.length), '', 7)}</dd></div>
                  <div><dt>Triangles</dt><dd>{formatMetric(Number(mesh.mesh_info.element_count ?? mesh.triangles.length), '', 7)}</dd></div>
                  <div>
                    <dt>Corner refinement</dt>
                    <dd className={mesh.mesh_info.corner_refinement === true ? 'pass' : ''}>
                      {mesh.mesh_info.corner_refinement === true ? 'Applied' : 'Off'}
                    </dd>
                  </div>
                  <div>
                    <dt>Magnet corner size</dt>
                    <dd>{formatMetric(Number(mesh.mesh_info.corner_size_mm), 'mm')}</dd>
                  </div>
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
              <div className="halbach-fidelity-card">{HALBACH_AXIAL_NOTICE}</div>
            </>
          )}

          {stage === 'report' && report && (
            <>
              <div className="halbach-panel-title">
                <span className="eyebrow">Report</span>
                <h2>Field solution</h2>
                <p>Generic Magneto2D result with Halbach metrics</p>
              </div>
              {axialOutputsStale && (
                <div className="halbach-issue warning" role="status">
                  <strong>Axial outputs stale</strong>
                  <span>
                    The 2D field remains valid, but volume, mass, extruded energy,
                    3D extrusion scaling, and all exports require recomputation.
                  </span>
                </div>
              )}
              <dl className="halbach-report-metrics">
                <div className="hero"><dt>Mean bore field</dt><dd>{formatMetric(report.bore_field.b_parallel_t.mean, 'T', 6)}</dd></div>
                <div><dt>Direction</dt><dd>{formatMetric(
                  report.bore_field.requested_field_direction_deg
                    + report.bore_field.mean_field_direction_error_deg,
                  '°',
                )}</dd></div>
                <div><dt>Direction error</dt><dd>{formatMetric(report.bore_field.mean_field_direction_error_deg, '°')}</dd></div>
                <div><dt>Uniformity</dt><dd>{formatMetric(report.bore_field.uniformity_ppm, 'ppm')}</dd></div>
                <div><dt>Leakage RMS</dt><dd>{formatMetric(report.external_leakage.rms_b_t, 'T')}</dd></div>
                <div><dt>Leakage ratio</dt><dd>{formatMetric(report.external_leakage.leakage_ratio_rms)}</dd></div>
                <div><dt>Magnet volume</dt><dd>{formatMetric(report.magnet.volume_m3 * 1e6, 'cm³')}</dd></div>
                <div><dt>Magnet mass</dt><dd>{formatMetric(report.magnet.mass_kg, 'kg')}</dd></div>
              </dl>
              <details className="halbach-report-details">
                <summary>Timing and provenance</summary>
                {Object.entries(report.timings_ms).map(([label, value]) => (
                  <div key={label}><span>{label.replace(/_/g, ' ')}</span><strong>{formatMetric(value, 'ms')}</strong></div>
                ))}
                <div><span>Peak memory</span><strong>{formatMetric(report.peak_memory_bytes == null ? null : report.peak_memory_bytes / 1048576, 'MiB')}</strong></div>
              </details>
              <div className="halbach-exports" aria-label="Report exports">
                {([
                  ['report', 'Halbach JSON'],
                  ['problem', 'Problem JSON'],
                  ['field', 'Field JSON'],
                  ['csv', 'Samples CSV'],
                  ['svg', 'Field SVG'],
                  ['png', 'Field PNG'],
                  ['pdf', 'Report PDF'],
                ] as Array<[HalbachExportKind, string]>).map(([kind, label]) => (
                  <button
                    key={kind}
                    type="button"
                    disabled={axialOutputsStale}
                    title={axialOutputsStale ? 'Recompute axial-derived outputs before export.' : undefined}
                    onClick={() => void exportResult(kind)}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div className="halbach-fidelity-card">{report.model.notice}</div>
            </>
          )}

          {validationIssues.length > 0 && localErrors.length === 0 && (
            <div className="halbach-issue error">
              <strong>Backend validation</strong>
              <span>{validationIssues.map((issue) => `${issue.field}: ${issue.message}`).join('; ')}</span>
            </div>
          )}
          {error && <div className="halbach-error-banner" role="alert">{error}</div>}
        </aside>
      </main>
    </div>
  );
}

function savedCylindricalDraft(
  initialConfig?: HalbachArrayConfig | LinearHalbachArrayConfig,
): HalbachArrayConfig | undefined {
  if (initialConfig?.kind === 'halbach_array_config') return initialConfig;
  try {
    const raw = window.localStorage?.getItem('openem_halbach_autosave');
    const parsed = raw ? JSON.parse(raw) as Partial<HalbachProjectFile> : null;
    return parsed?.halbach_config?.kind === 'halbach_array_config'
      ? parsed.halbach_config
      : undefined;
  } catch {
    return undefined;
  }
}

function savedLinearDraft(
  initialConfig?: HalbachArrayConfig | LinearHalbachArrayConfig,
): LinearHalbachArrayConfig | undefined {
  if (initialConfig?.kind === 'linear_halbach_array_config') return initialConfig;
  try {
    const raw = window.localStorage?.getItem('openem_linear_halbach_autosave');
    const parsed = raw
      ? JSON.parse(raw) as { halbach_config?: LinearHalbachArrayConfig }
      : null;
    return parsed?.halbach_config?.kind === 'linear_halbach_array_config'
      ? parsed.halbach_config
      : undefined;
  } catch {
    return undefined;
  }
}

export function HalbachWorkspace({
  onHome,
  initialConfig,
  connectionStatus = 'online',
}: HalbachWorkspaceProps) {
  const [topology, setTopology] = useState<HalbachTopology>(
    initialConfig?.kind === 'linear_halbach_array_config' ? 'linear' : 'cylindrical',
  );
  const cylindricalDraft = useMemo(
    () => savedCylindricalDraft(initialConfig),
    [initialConfig, topology],
  );
  const linearDraft = useMemo(
    () => savedLinearDraft(initialConfig),
    [initialConfig, topology],
  );

  if (topology === 'linear') {
    return (
      <LinearHalbachWorkspace
        onHome={onHome}
        onTopologyChange={setTopology}
        initialConfig={linearDraft}
        connectionStatus={connectionStatus}
      />
    );
  }
  return (
    <CylindricalHalbachWorkspace
      onHome={onHome}
      onTopologyChange={setTopology}
      initialConfig={cylindricalDraft}
      connectionStatus={connectionStatus}
    />
  );
}
