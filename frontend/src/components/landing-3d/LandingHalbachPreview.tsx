import React from 'react';

import { LinearHalbach3DViewer } from '../../public/halbach/LinearHalbach3DViewer';
import {
  cloneDefaultLinearHalbachConfig,
  type HalbachContourLevel,
  type LinearHalbachArrayConfig,
  type LinearHalbachMeshPreview,
  type LinearHalbachReport,
} from '../../public/halbach/types';
import {
  LandingPreviewModeControl,
  type LandingPreviewMode,
} from './LandingPreviewModeControl';

const AUTO_ADVANCE_MS = 2_600;

const LANDING_LINEAR_HALBACH_CONFIG: LinearHalbachArrayConfig = {
  ...cloneDefaultLinearHalbachConfig(),
  geometry: {
    ...cloneDefaultLinearHalbachConfig().geometry,
    out_of_plane_depth: 12,
    period_count: 3,
    block_gap: 0.8,
  },
};

const PREVIEW_STAGES = [
  'geometry',
  'mesh',
  'field',
] as const satisfies readonly LandingPreviewMode[];

type LandingGmshMeshFixture = LinearHalbachMeshPreview & {
  provenance: {
    generator: string;
    mesh_engine: 'Gmsh';
    gmsh_version: string;
    geometry_pipeline: string;
    mesh_pipeline: string;
    runtime_use: string;
  };
};

interface LandingMagneto2dFieldFixture {
  kind: 'linear_halbach_landing_field_fixture';
  version: '1.0';
  provenance: {
    generator: string;
    solver: 'Magneto2D';
    mesh_engine: 'Gmsh';
    gmsh_version: string;
    problem_sha256: string;
    geometry_hash: string;
    mesh_hash: string;
    runtime_use: string;
  };
  model: LinearHalbachReport['model'];
  working_field: LinearHalbachReport['working_field'];
  leakage_field: LinearHalbachReport['leakage_field'];
  one_sidedness: LinearHalbachReport['one_sidedness'];
  magnet: LinearHalbachReport['magnet'];
  samples: LinearHalbachReport['samples'];
  field_data: {
    element_fields_t: Array<[number, number, number]>;
    az_nodal_t_m: number[];
    contours: HalbachContourLevel[];
    available_views: string[];
  };
  warnings: string[];
}

function buildLandingPreviewData(
  config: LinearHalbachArrayConfig,
  mesh: LandingGmshMeshFixture,
  fieldFixture: LandingMagneto2dFieldFixture,
): {
  mesh: LinearHalbachMeshPreview;
  report: LinearHalbachReport;
} {
  if (
    mesh.mesh_hash !== fieldFixture.provenance.mesh_hash
    || mesh.geometry_hash !== fieldFixture.provenance.geometry_hash
    || mesh.magnetostatic_problem_sha256 !== fieldFixture.provenance.problem_sha256
  ) {
    throw new Error('Landing Halbach field fixture does not match its Gmsh inputs');
  }
  if (
    fieldFixture.field_data.element_fields_t.length !== mesh.triangles.length
    || fieldFixture.field_data.az_nodal_t_m.length !== mesh.nodes_mm.length
  ) {
    throw new Error('Landing Halbach field fixture dimensions are inconsistent');
  }

  const report: LinearHalbachReport = {
    openem_schema_kind: 'linear_halbach_solution_report',
    openem_schema_version: '1.0',
    configuration: config,
    model: fieldFixture.model,
    working_field: fieldFixture.working_field,
    leakage_field: fieldFixture.leakage_field,
    one_sidedness: fieldFixture.one_sidedness,
    magnet: fieldFixture.magnet,
    samples: fieldFixture.samples,
    field_data: {
      nodes_mm: mesh.nodes_mm,
      triangles: mesh.triangles,
      region_ids: mesh.regions,
      element_fields_t: fieldFixture.field_data.element_fields_t.map(([bx, by, b_mag]) => ({
        bx,
        by,
        b_mag,
      })),
      az_nodal_t_m: fieldFixture.field_data.az_nodal_t_m,
      contours: fieldFixture.field_data.contours,
      available_views: fieldFixture.field_data.available_views,
    },
    timings_ms: {},
    peak_memory_bytes: null,
    artifacts: {
      source: 'checked_in_real_solver_fixture',
      solver: fieldFixture.provenance.solver,
      mesh_source: mesh.mesh_info.mesh_source,
      mesh_hash: mesh.mesh_hash,
    },
    magnetostatic_problem: {
      source: 'checked_in_real_solver_fixture',
      sha256: fieldFixture.provenance.problem_sha256,
    },
    generic_field_report: {
      solver: fieldFixture.provenance.solver,
      mesh_engine: fieldFixture.provenance.mesh_engine,
    },
    warnings: fieldFixture.warnings,
  };

  return { mesh, report };
}

export function LandingHalbachPreview() {
  const [selectedMagnet, setSelectedMagnet] = React.useState<number | null>(null);
  const [activeStageIndex, setActiveStageIndex] = React.useState(0);
  const [isOrbiting, setIsOrbiting] = React.useState(false);
  const [hasManualSelection, setHasManualSelection] = React.useState(false);
  const [loadError, setLoadError] = React.useState(false);
  const [previewData, setPreviewData] = React.useState<ReturnType<typeof buildLandingPreviewData> | null>(null);
  const activeMode = PREVIEW_STAGES[activeStageIndex];
  const viewportMode = !previewData ? 'geometry' : activeMode;

  React.useEffect(() => {
    let cancelled = false;
    Promise.all([
      import('./hero_linear_halbach_mesh.gmsh.json'),
      import('./hero_linear_halbach_field.magneto2d.json'),
    ])
      .then(([meshModule, fieldModule]) => {
        if (cancelled) return;
        setPreviewData(buildLandingPreviewData(
          LANDING_LINEAR_HALBACH_CONFIG,
          meshModule.default as unknown as LandingGmshMeshFixture,
          fieldModule.default as unknown as LandingMagneto2dFieldFixture,
        ));
      })
      .catch(() => {
        if (!cancelled) {
          setLoadError(true);
          setActiveStageIndex(0);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  React.useEffect(() => {
    if (
      !previewData
      || isOrbiting
      || hasManualSelection
      || window.matchMedia('(prefers-reduced-motion: reduce)').matches
    ) return undefined;
    const timer = window.setInterval(() => {
      setActiveStageIndex((current) => (current + 1) % PREVIEW_STAGES.length);
    }, AUTO_ADVANCE_MS);
    return () => window.clearInterval(timer);
  }, [hasManualSelection, isOrbiting, previewData]);

  const selectMode = (mode: LandingPreviewMode) => {
    const nextIndex = PREVIEW_STAGES.indexOf(mode);
    if (nextIndex < 0 || (mode !== 'geometry' && !previewData)) return;
    setActiveStageIndex(nextIndex);
    setHasManualSelection(true);
  };

  return (
    <div
      className="landing-halbach-preview"
      data-preview-stage={activeMode}
      data-mesh-source={previewData?.mesh.mesh_info.mesh_source}
      data-mesh-hash={previewData?.mesh.mesh_hash}
      data-field-source={previewData ? 'magneto2d' : undefined}
      onPointerDown={() => setIsOrbiting(true)}
      onPointerUp={() => setIsOrbiting(false)}
      onPointerCancel={() => setIsOrbiting(false)}
      onPointerLeave={() => setIsOrbiting(false)}
    >
      <LinearHalbach3DViewer
        config={LANDING_LINEAR_HALBACH_CONFIG}
        mesh={previewData?.mesh ?? null}
        report={previewData?.report ?? null}
        resultView="magnitude"
        viewportMode={viewportMode}
        selectedMagnet={selectedMagnet}
        onSelectMagnet={setSelectedMagnet}
        showHeatmap={activeMode === 'field'}
        showMeshOverlay={activeMode === 'field'}
        showFieldLines={activeMode === 'field'}
        fieldLineDensity="medium"
        showMagnetization={activeMode !== 'field'}
        showProbeOverlays={false}
        presentation="hero"
      />
      <LandingPreviewModeControl
        activeMode={activeMode}
        ariaLabel="Halbach preview view"
        onSelect={selectMode}
        disabledModes={loadError || !previewData ? ['mesh', 'field'] : []}
      />
    </div>
  );
}
