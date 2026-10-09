import React from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import {
  LandingPreviewModeControl,
  type LandingPreviewMode,
} from './LandingPreviewModeControl';
import { resolveLandingSolvedPlayback } from './solvedPlayback';
import { buildConcentratedCoil } from '../../public/coil3d';

const BACK_EMF_PHASE_COLORS = { A: '#f59e0b', B: '#34d399', C: '#a78bfa' } as const;
const DESIGN_MAGNET_N_FILL = '#e53e3e';
const DESIGN_MAGNET_S_FILL = '#3182ce';
// Match `.public-field-result-line` in the product solve view.
const SOLVED_FIELD_LINE_COLOR = 0xffd166;

const IDLE_ORBIT_LIMIT_RAD = THREE.MathUtils.degToRad(75);
const IDLE_ORBIT_EDGE_EPSILON_RAD = THREE.MathUtils.degToRad(0.5);
const IDLE_ORBIT_SPEED = 0.42;
const ROTOR_SPIN_RADIANS_PER_SECOND = 0.15;
const IMMERSIVE_PORTRAIT_MAX_DISTANCE = 420;

const STACK = 50;
const VISUAL_SCALE = 0.5;
const STATOR_OD_R = 50;
const STATOR_YOKE_ID_R = 41;
const TOOTH_BORE_R = 30;
const TOOTH_SHOULDER_R = 31.25;
const TOOTH_YOKE_R = 41;
const SLOT_BODY_OPENING = 6 * VISUAL_SCALE;
const TOOTH_SHOE_OVERHANG = 1.5 * VISUAL_SCALE;
const YOKE_TOOTH_WIDTH = 26.2 * VISUAL_SCALE;
const MAGNET_OUT_R = 29.5;
const MAGNET_IN_R = 27.5;
const SHAFT_R = 2.75;
const HUB_R = 8;
const POLES = 8;
const SLOTS = 12;
const SLOT_PITCH_RAD = (Math.PI * 2) / SLOTS;
const TOOTH_BODY_BORE_HALF_ANGLE = SLOT_PITCH_RAD / 2
  - (SLOT_BODY_OPENING / 2) / TOOTH_BORE_R;
const TOOTH_TIP_HALF_ANGLE = TOOTH_BODY_BORE_HALF_ANGLE
  + TOOTH_SHOE_OVERHANG / TOOTH_BORE_R;
const TOOTH_YOKE_HALF_ANGLE = (YOKE_TOOTH_WIDTH / 2) / TOOTH_YOKE_R;
const TOOTH_SHOULDER_FRACTION = (TOOTH_SHOULDER_R - TOOTH_BORE_R)
  / (TOOTH_YOKE_R - TOOTH_BORE_R);
const TOOTH_SHOULDER_HALF_ANGLE = TOOTH_BODY_BORE_HALF_ANGLE
  + TOOTH_SHOULDER_FRACTION * (TOOTH_YOKE_HALF_ANGLE - TOOTH_BODY_BORE_HALF_ANGLE);
const SOLVED_HEATMAP_PALETTE = [
  0x102a56,
  0x175d9f,
  0x18a6c9,
  0x45d483,
  0xf1dc43,
  0xf59e0b,
  0xef4444,
] as const;

interface MeshFixture {
  source: string;
  nodes: number;
  triangles: number;
  edges: number;
  coordinateScale: number;
  outerRadius: number;
  coordinates: string;
  edgeIndices: string;
}

type QuantizedPoint = [number, number];

interface FieldFixture {
  slotPeriodMechanicalDeg: number;
  frameStepMechanicalDeg: number;
  coordinateScale: number;
  levels: number[];
  frames: Array<{
    angleMechanicalDeg: number;
    levels: QuantizedPoint[][][];
  }>;
}

interface HeatmapFixture {
  schemaVersion: 'coilem.landing_b_heatmap.v2';
  source: string;
  solver: string;
  slotPeriodMechanicalDeg: number;
  frameStepMechanicalDeg: number;
  width: number;
  height: number;
  extentRadius: number;
  displayMaxTesla: number;
  frames: Array<{
    angleMechanicalDeg: number;
    values: string;
  }>;
}

interface ViewState {
  solid: number;
  wire: number;
  mesh: number;
  airgap: number;
  labels: number;
  flux: number;
  heatmap: number;
}

const VIEW_STATES: ViewState[] = [
  { solid: 1, wire: 0.10, mesh: 0, airgap: 0.46, labels: 1, flux: 0, heatmap: 0 },
  { solid: 0.26, wire: 0.18, mesh: 0.42, airgap: 0.10, labels: 0, flux: 0, heatmap: 0 },
  { solid: 0.56, wire: 0.04, mesh: 0.13, airgap: 0.14, labels: 0, flux: 1, heatmap: 1 },
];
const PREVIEW_MODES = ['geometry', 'mesh', 'field'] as const satisfies readonly LandingPreviewMode[];
const SHAFT_OVERHANG_SCALE = 0.5;
const MOTOR_VIEW_DISTANCE_SCALE = 1.06;
const MOTOR_PORTRAIT_DISTANCE_SCALE = 1.3;
// Keep the engineering overlays just ahead of the exploded stator face.
const ANALYSIS_LAYER_EXPLODED_OFFSET_Z = 180;
const EXPLODED_SCENE_OFFSET_Z = -45;

type LandingPartId = 'stator' | 'windings' | 'airgap' | 'magnets' | 'rotor' | 'bearings' | 'shaft';

const LANDING_PARTS: ReadonlyArray<{ id: LandingPartId; label: string }> = [
  { id: 'stator', label: 'Stator' },
  { id: 'windings', label: 'Windings' },
  { id: 'airgap', label: 'Air gap' },
  { id: 'magnets', label: 'Magnets' },
  { id: 'rotor', label: 'Rotor' },
  { id: 'bearings', label: 'Bearings' },
  { id: 'shaft', label: 'Shaft' },
];

const MODE_HIDDEN_PARTS: Record<LandingPreviewMode, readonly LandingPartId[]> = {
  geometry: [],
  mesh: ['windings', 'bearings', 'shaft'],
  field: ['windings', 'rotor', 'bearings', 'shaft'],
};

const EXPLODE_PHASES: Record<LandingPartId, readonly [number, number]> = {
  stator: [0, 0.18],
  windings: [0.18, 0.36],
  airgap: [0.36, 0.54],
  magnets: [0.54, 0.72],
  rotor: [0.72, 0.80],
  bearings: [0.80, 0.92],
  shaft: [0.92, 1],
};

const createDefaultPartVisibility = (): Record<LandingPartId, boolean> => ({
  stator: true,
  windings: true,
  airgap: true,
  magnets: true,
  rotor: true,
  bearings: true,
  shaft: true,
});

const renderTargetColor = (hex: string, scale = 0.72) => {
  const value = hex.replace('#', '');
  const channel = (offset: number) => Math.max(
    0,
    Math.min(255, Math.round(Number.parseInt(value.slice(offset, offset + 2), 16) * scale)),
  );
  return (channel(0) << 16) | (channel(2) << 8) | channel(4);
};

export const Landing3DPreview: React.FC = () => {
  const canvasRef = React.useRef<HTMLCanvasElement | null>(null);
  const stageRef = React.useRef<HTMLDivElement | null>(null);
  const fullscreenButtonRef = React.useRef<HTMLButtonElement | null>(null);
  const immersiveRef = React.useRef(false);
  const explodeAmountRef = React.useRef(0);
  const touchStartRef = React.useRef<{ pointerId: number; x: number; y: number } | null>(null);
  const lastTouchTapRef = React.useRef(0);
  const suppressDoubleClickUntilRef = React.useRef(0);
  const activeStepRef = React.useRef(0);
  const partVisibilityRef = React.useRef<Record<LandingPartId, boolean>>(createDefaultPartVisibility());
  const assetLoaderRef = React.useRef<{
    mesh: () => void;
    field: () => void;
  } | null>(null);
  const sceneStateRef = React.useRef<{
    rotorGroup: THREE.Group;
    wireRotorGroup: THREE.Group;
  } | null>(null);
  const [activeStep, setActiveStep] = React.useState(0);
  const [partVisibility, setPartVisibility] = React.useState<Record<LandingPartId, boolean>>(
    createDefaultPartVisibility,
  );
  const [loadError, setLoadError] = React.useState(false);
  const [isImmersive, setIsImmersive] = React.useState(false);
  const [explodeAmount, setExplodeAmount] = React.useState(0);

  React.useEffect(() => {
    activeStepRef.current = activeStep;
  }, [activeStep]);

  React.useEffect(() => {
    partVisibilityRef.current = partVisibility;
  }, [partVisibility]);

  React.useEffect(() => {
    immersiveRef.current = isImmersive;
  }, [isImmersive]);

  React.useEffect(() => {
    explodeAmountRef.current = explodeAmount;
  }, [explodeAmount]);

  React.useEffect(() => {
    if (activeStep === 1) assetLoaderRef.current?.mesh();
    if (activeStep === 2) assetLoaderRef.current?.field();
  }, [activeStep]);

  const activeMode = PREVIEW_MODES[activeStep];
  const selectMode = (mode: LandingPreviewMode) => {
    const nextIndex = PREVIEW_MODES.indexOf(mode);
    if (nextIndex < 0) return;
    setActiveStep(nextIndex);
  };

  const togglePart = (partId: LandingPartId) => {
    setPartVisibility((current) => ({ ...current, [partId]: !current[partId] }));
  };

  const enterImmersive = React.useCallback(() => {
    const stage = stageRef.current;
    setIsImmersive(true);
    if (!stage || document.fullscreenElement === stage || !stage.requestFullscreen) return;
    void stage.requestFullscreen({ navigationUI: 'hide' }).catch(() => {
      // CSS fullscreen remains available when the browser declines the native API.
    });
  }, []);

  const exitImmersive = React.useCallback(() => {
    const stage = stageRef.current;
    if (stage && document.fullscreenElement === stage && document.exitFullscreen) {
      void document.exitFullscreen().finally(() => {
        setIsImmersive(false);
        setExplodeAmount(0);
      });
      return;
    }
    setIsImmersive(false);
    setExplodeAmount(0);
  }, []);

  const toggleImmersive = React.useCallback(() => {
    if (immersiveRef.current) exitImmersive();
    else enterImmersive();
  }, [enterImmersive, exitImmersive]);

  React.useEffect(() => {
    const handleFullscreenChange = () => {
      const stage = stageRef.current;
      if (stage && document.fullscreenElement === stage) {
        setIsImmersive(true);
      } else if (immersiveRef.current && document.fullscreenElement === null) {
        setIsImmersive(false);
        setExplodeAmount(0);
      }
    };
    document.addEventListener('fullscreenchange', handleFullscreenChange);
    return () => document.removeEventListener('fullscreenchange', handleFullscreenChange);
  }, []);

  React.useEffect(() => {
    if (!isImmersive) return undefined;
    const previousBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') exitImmersive();
    };
    window.addEventListener('keydown', handleKeyDown);
    window.requestAnimationFrame(() => fullscreenButtonRef.current?.focus());
    return () => {
      document.body.style.overflow = previousBodyOverflow;
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [exitImmersive, isImmersive]);

  const handleStagePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.pointerType !== 'touch' || (event.target as HTMLElement).closest('button')) return;
    touchStartRef.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY };
  };

  const handleStagePointerUp = (event: React.PointerEvent<HTMLDivElement>) => {
    const start = touchStartRef.current;
    touchStartRef.current = null;
    if (!start || start.pointerId !== event.pointerId) return;
    const deltaX = event.clientX - start.x;
    const deltaY = event.clientY - start.y;
    if (Math.abs(deltaX) >= 24 && Math.abs(deltaX) > Math.abs(deltaY) * 1.2) {
      stageRef.current?.dispatchEvent(new CustomEvent('coilem:landing-orbit-started', { bubbles: true }));
      return;
    }
    if (Math.hypot(deltaX, deltaY) > 14) return;
    const now = performance.now();
    if (now - lastTouchTapRef.current <= 360) {
      lastTouchTapRef.current = 0;
      suppressDoubleClickUntilRef.current = now + 500;
      toggleImmersive();
      return;
    }
    lastTouchTapRef.current = now;
  };

  const handleStageDoubleClick = (event: React.MouseEvent<HTMLDivElement>) => {
    if ((event.target as HTMLElement).closest('button')) return;
    if (performance.now() < suppressDoubleClickUntilRef.current) return;
    toggleImmersive();
  };

  React.useEffect(() => {
    const canvas = canvasRef.current;
    const stage = stageRef.current;
    if (!canvas || !stage) return undefined;

    let cancelled = false;
    let disposeScene = () => {};

    const initialize = async () => {
      const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = 1.02;
      renderer.shadowMap.enabled = true;
      renderer.shadowMap.type = THREE.PCFShadowMap;

      const scene = new THREE.Scene();
      const pmrem = new THREE.PMREMGenerator(renderer);
      const environmentTarget = pmrem.fromScene(new RoomEnvironment(), 0.04);
      scene.environment = environmentTarget.texture;
      scene.environmentIntensity = 0.62;

      const cameraFitScale = MOTOR_VIEW_DISTANCE_SCALE
        * (stage.clientHeight > stage.clientWidth ? MOTOR_PORTRAIT_DISTANCE_SCALE : 1);
      const camera = new THREE.PerspectiveCamera(36, 1, 1, 2_000);
      camera.position.set(
        STATOR_OD_R * 2.45 * cameraFitScale,
        STATOR_OD_R * 1.8 * cameraFitScale,
        STATOR_OD_R * 2.7 * cameraFitScale,
      );

      const controls = new OrbitControls(camera, canvas);
      controls.enableDamping = true;
      controls.dampingFactor = 0.06;
      controls.enablePan = false;
      controls.minDistance = 72;
      controls.maxDistance = 280;
      controls.minAzimuthAngle = -IDLE_ORBIT_LIMIT_RAD;
      controls.maxAzimuthAngle = IDLE_ORBIT_LIMIT_RAD;
      controls.autoRotate = !reducedMotion;
      controls.autoRotateSpeed = IDLE_ORBIT_SPEED;

      scene.add(new THREE.AmbientLight(0xffe4c4, 0.30));
      scene.add(new THREE.HemisphereLight(0xffe2bd, 0x171310, 0.52));
      const key = new THREE.DirectionalLight(0xffdcae, 1.62);
      key.position.set(STATOR_OD_R * 2, STATOR_OD_R * 2.4, STATOR_OD_R * 2.6);
      key.castShadow = true;
      key.shadow.mapSize.set(1_024, 1_024);
      key.shadow.camera.left = -STATOR_OD_R * 2.4;
      key.shadow.camera.right = STATOR_OD_R * 2.4;
      key.shadow.camera.top = STATOR_OD_R * 2.4;
      key.shadow.camera.bottom = -STATOR_OD_R * 2.4;
      key.shadow.camera.near = 1;
      key.shadow.camera.far = STATOR_OD_R * 8;
      scene.add(key);
      const fill = new THREE.DirectionalLight(0xbcd4f0, 0.56);
      fill.position.set(-STATOR_OD_R * 2.2, STATOR_OD_R * 0.8, STATOR_OD_R * 1.4);
      scene.add(fill);
      const rim = new THREE.DirectionalLight(0x67e8f9, 0.58);
      rim.position.set(-STATOR_OD_R * 2, -STATOR_OD_R, STATOR_OD_R * 1.2);
      scene.add(rim);
      const warmRim = new THREE.DirectionalLight(0xffb347, 0.42);
      warmRim.position.set(STATOR_OD_R * 0.8, -STATOR_OD_R * 2.1, -STATOR_OD_R);
      scene.add(warmRim);

      const solidMats: Array<THREE.MeshStandardMaterial | THREE.MeshBasicMaterial> = [];
      const wireMats: THREE.LineBasicMaterial[] = [];
      const airgapMats: THREE.MeshBasicMaterial[] = [];
      const labelMats: THREE.SpriteMaterial[] = [];
      const meshMats: THREE.LineBasicMaterial[] = [];
      const meshLineObjects: THREE.LineSegments[] = [];
      const heatmapMats: THREE.MeshBasicMaterial[] = [];
      const heatmapFrameMeshes: THREE.Mesh[] = [];
      const fieldFrameMaterials: THREE.LineBasicMaterial[] = [];
      const fieldFrameMeshes: THREE.LineSegments[] = [];
      const textures: THREE.Texture[] = [];
      const femGroup = new THREE.Group();
      const rotorFemGroup = new THREE.Group();
      const heatmapGroup = new THREE.Group();
      const fluxGroup = new THREE.Group();
      femGroup.add(rotorFemGroup);

      const extrude = (shape: THREE.Shape, depth = STACK) => {
        const geometry = new THREE.ExtrudeGeometry(shape, {
          depth,
          bevelEnabled: false,
          curveSegments: 72,
        });
        geometry.translate(0, 0, -depth / 2);
        return geometry;
      };

      const ringShape = (outerRadius: number, innerRadius: number) => {
        const shape = new THREE.Shape();
        shape.absarc(0, 0, outerRadius, 0, Math.PI * 2, false);
        const hole = new THREE.Path();
        hole.absarc(0, 0, innerRadius, 0, Math.PI * 2, true);
        shape.holes.push(hole);
        return shape;
      };

      const toothGeometry = () => {
        const shape = new THREE.Shape();
        const polarPoint = (radius: number, angleRad: number) => new THREE.Vector2(
          Math.cos(angleRad) * radius,
          Math.sin(angleRad) * radius,
        );
        const boreStart = polarPoint(TOOTH_BORE_R, -TOOTH_TIP_HALF_ANGLE);
        shape.moveTo(boreStart.x, boreStart.y);
        shape.absarc(0, 0, TOOTH_BORE_R, -TOOTH_TIP_HALF_ANGLE, TOOTH_TIP_HALF_ANGLE, false);
        shape.lineTo(...polarPoint(TOOTH_SHOULDER_R, TOOTH_TIP_HALF_ANGLE).toArray());
        shape.lineTo(...polarPoint(TOOTH_SHOULDER_R, TOOTH_SHOULDER_HALF_ANGLE).toArray());
        shape.lineTo(...polarPoint(TOOTH_YOKE_R, TOOTH_YOKE_HALF_ANGLE).toArray());
        shape.absarc(0, 0, TOOTH_YOKE_R, TOOTH_YOKE_HALF_ANGLE, -TOOTH_YOKE_HALF_ANGLE, true);
        shape.lineTo(...polarPoint(TOOTH_SHOULDER_R, -TOOTH_SHOULDER_HALF_ANGLE).toArray());
        shape.lineTo(...polarPoint(TOOTH_SHOULDER_R, -TOOTH_TIP_HALF_ANGLE).toArray());
        shape.closePath();
        return extrude(shape);
      };

      const magnetGeometry = (innerRadius: number, outerRadius: number, halfSpanDeg: number) => {
        const halfSpan = THREE.MathUtils.degToRad(halfSpanDeg);
        const shape = new THREE.Shape();
        shape.absarc(0, 0, outerRadius, Math.PI / 2 - halfSpan, Math.PI / 2 + halfSpan, false);
        shape.absarc(0, 0, innerRadius, Math.PI / 2 + halfSpan, Math.PI / 2 - halfSpan, true);
        shape.closePath();
        return extrude(shape);
      };

      const physical = (options: THREE.MeshPhysicalMaterialParameters, fieldOpacityScale = 1) => {
        const material = new THREE.MeshPhysicalMaterial({ transparent: true, ...options });
        material.userData.baseOpacity = options.opacity ?? 1;
        material.userData.fieldOpacityScale = fieldOpacityScale;
        solidMats.push(material);
        return material;
      };

      const wire = (color: THREE.ColorRepresentation, baseOpacity = 1) => {
        const material = new THREE.LineBasicMaterial({ transparent: true, opacity: 0, color });
        material.userData.baseOpacity = baseOpacity;
        wireMats.push(material);
        return material;
      };

      const makeGridTexture = () => {
        const textureCanvas = document.createElement('canvas');
        textureCanvas.width = textureCanvas.height = 96;
        const context = textureCanvas.getContext('2d');
        if (context) {
          context.fillStyle = '#303844';
          context.fillRect(0, 0, 96, 96);
          context.strokeStyle = 'rgba(194, 205, 220, 0.12)';
          context.lineWidth = 1;
          for (let offset = -96; offset < 192; offset += 12) {
            context.beginPath(); context.moveTo(offset, 0); context.lineTo(offset + 96, 96); context.stroke();
            context.beginPath(); context.moveTo(offset + 96, 0); context.lineTo(offset, 96); context.stroke();
          }
        }
        const texture = new THREE.CanvasTexture(textureCanvas);
        texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
        texture.repeat.set(2.2, 2.2);
        texture.colorSpace = THREE.SRGBColorSpace;
        textures.push(texture);
        return texture;
      };

      const makeLaminationTexture = () => {
        const textureCanvas = document.createElement('canvas');
        textureCanvas.width = 12;
        textureCanvas.height = 96;
        const context = textureCanvas.getContext('2d');
        if (context) {
          context.clearRect(0, 0, 12, 96);
          context.strokeStyle = 'rgba(215, 225, 238, 0.5)';
          context.lineWidth = 1;
          for (let y = 2; y < 96; y += 6) {
            context.beginPath(); context.moveTo(0, y); context.lineTo(12, y); context.stroke();
          }
        }
        const texture = new THREE.CanvasTexture(textureCanvas);
        texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
        texture.repeat.set(8, 1);
        textures.push(texture);
        return texture;
      };

      const makePoleLabel = (text: string, color: string) => {
        const labelCanvas = document.createElement('canvas');
        labelCanvas.width = labelCanvas.height = 128;
        const context = labelCanvas.getContext('2d');
        if (context) {
          context.clearRect(0, 0, 128, 128);
          context.fillStyle = 'rgba(8, 12, 18, 0.64)';
          context.beginPath(); context.arc(64, 64, 42, 0, Math.PI * 2); context.fill();
          context.strokeStyle = color; context.lineWidth = 6; context.stroke();
          context.fillStyle = '#ffffff';
          context.font = '700 58px Inter, sans-serif';
          context.textAlign = 'center'; context.textBaseline = 'middle'; context.fillText(text, 64, 67);
        }
        const texture = new THREE.CanvasTexture(labelCanvas);
        texture.colorSpace = THREE.SRGBColorSpace;
        textures.push(texture);
        const material = new THREE.SpriteMaterial({
          map: texture,
          transparent: true,
          depthTest: true,
          depthWrite: false,
          opacity: 1,
        });
        material.userData.landingPart = 'magnets';
        labelMats.push(material);
        const sprite = new THREE.Sprite(material);
        sprite.scale.setScalar(5.2);
        sprite.renderOrder = 1;
        return sprite;
      };

      const enamelledCopper = (phaseColor: string) => physical({
        color: new THREE.Color(renderTargetColor(phaseColor)).lerp(new THREE.Color(0xc9722e), 0.1),
        metalness: 0.45,
        roughness: 0.3,
        clearcoat: 0.4,
        clearcoatRoughness: 0.28,
      }, 0.4);
      const materials = {
        stator: physical({ color: renderTargetColor('#8fa3b8'), metalness: 0.62, roughness: 0.47, clearcoat: 0.06, clearcoatRoughness: 0.45, envMapIntensity: 0.55 }, 0.38),
        tooth: physical({ color: renderTargetColor('#a3b5c8'), metalness: 0.56, roughness: 0.48, clearcoat: 0.05, clearcoatRoughness: 0.45, envMapIntensity: 0.55 }, 0.38),
        phaseA: enamelledCopper(BACK_EMF_PHASE_COLORS.A),
        phaseB: enamelledCopper(BACK_EMF_PHASE_COLORS.B),
        phaseC: enamelledCopper(BACK_EMF_PHASE_COLORS.C),
        liner: physical({ color: 0xf1ead8, metalness: 0.02, roughness: 0.72, clearcoat: 0.06, clearcoatRoughness: 0.5 }, 0.26),
        rotor: physical({ color: 0xffffff, map: makeGridTexture(), metalness: 0.68, roughness: 0.46, clearcoat: 0.05, clearcoatRoughness: 0.5, envMapIntensity: 0.55 }, 0.7),
        shaft: physical({ color: 0xaeb8c6, roughness: 0.5, clearcoat: 0.08 }, 0.62),
        shaftKey: physical({ color: 0x667383, metalness: 0.62, roughness: 0.36, clearcoat: 0.08 }, 0.62),
        sleeve: physical({
          color: 0xd7dde5,
          metalness: 0.9,
          roughness: 0.2,
          opacity: 0.16,
          side: THREE.DoubleSide,
          depthWrite: false,
        }, 0.5),
        magN: physical({ color: renderTargetColor('#ef4444'), emissive: 0x3d090c, metalness: 0.2, roughness: 0.28, clearcoat: 0.26, clearcoatRoughness: 0.3 }, 0.88),
        magS: physical({ color: renderTargetColor('#3b82f6'), emissive: 0x071d42, metalness: 0.2, roughness: 0.28, clearcoat: 0.26, clearcoatRoughness: 0.3 }, 0.88),
        oppositeN: physical({ color: renderTargetColor('#ef4444'), emissive: 0x5b0c12, metalness: 0.12, roughness: 0.24, clearcoat: 0.18 }, 0.88),
        oppositeS: physical({ color: renderTargetColor('#3b82f6'), emissive: 0x0a2d63, metalness: 0.12, roughness: 0.24, clearcoat: 0.18 }, 0.88),
        bearingRace: physical({ color: 0xa8b4c4, metalness: 0.82, roughness: 0.3, clearcoat: 0.12, clearcoatRoughness: 0.3, envMapIntensity: 0.5 }, 0.58),
        bearingBall: physical({ color: 0xccd5e1, metalness: 0.88, roughness: 0.22, clearcoat: 0.14, clearcoatRoughness: 0.28, envMapIntensity: 0.5 }, 0.58),
        bearingCage: physical({ color: 0xd0a557, metalness: 0.7, roughness: 0.36, clearcoat: 0.2 }, 0.58),
      };
      const tagMaterials = (partId: LandingPartId, taggedMaterials: THREE.Material[]) => {
        taggedMaterials.forEach((material) => {
          material.userData.landingPart = partId;
        });
      };
      tagMaterials('stator', [materials.stator, materials.tooth]);
      tagMaterials('windings', [materials.phaseA, materials.phaseB, materials.phaseC, materials.liner]);
      tagMaterials('magnets', [
        materials.sleeve,
        materials.magN,
        materials.magS,
        materials.oppositeN,
        materials.oppositeS,
      ]);
      tagMaterials('rotor', [materials.rotor]);
      tagMaterials('bearings', [materials.bearingRace, materials.bearingBall, materials.bearingCage]);
      tagMaterials('shaft', [materials.shaft, materials.shaftKey]);

      const motorGroup = new THREE.Group();
      const rotorGroup = new THREE.Group();
      const wireGroup = new THREE.Group();
      const wireRotorGroup = new THREE.Group();

      const addPart = (
        geometry: THREE.BufferGeometry,
        material: THREE.Material,
        wireColor: THREE.ColorRepresentation,
        parent: THREE.Group,
        wireParent: THREE.Group,
      ) => {
        parent.add(new THREE.Mesh(geometry, material));
        const edgeMaterial = wire(wireColor);
        edgeMaterial.userData.landingPart = material.userData.landingPart;
        wireParent.add(new THREE.LineSegments(new THREE.EdgesGeometry(geometry, 18), edgeMaterial));
      };

      addPart(extrude(ringShape(STATOR_OD_R, STATOR_YOKE_ID_R)), materials.stator, 0x7dd3fc, motorGroup, wireGroup);
      const toothGeo = toothGeometry();
      const concentratedCoil = buildConcentratedCoil({
        boreRadius: TOOTH_SHOULDER_R / VISUAL_SCALE,
        yokeInnerRadius: TOOTH_YOKE_R / VISUAL_SCALE,
        toothHalfAngleInnerRad: TOOTH_SHOULDER_HALF_ANGLE,
        toothHalfAngleOuterRad: TOOTH_YOKE_HALF_ANGLE,
        slotPitchRad: SLOT_PITCH_RAD,
        stackLength: STACK / VISUAL_SCALE,
        turnsPerCoil: 15,
      });
      for (let slot = 0; slot < SLOTS; slot += 1) {
        const angleDeg = (slot * 360) / SLOTS;
        const tooth = new THREE.Mesh(toothGeo, materials.tooth);
        tooth.rotation.z = THREE.MathUtils.degToRad(angleDeg);
        motorGroup.add(tooth);
        const toothWire = new THREE.LineSegments(new THREE.EdgesGeometry(toothGeo, 18), wire(0x7dd3fc));
        (toothWire.material as THREE.Material).userData.landingPart = 'stator';
        toothWire.rotation.z = tooth.rotation.z;
        wireGroup.add(toothWire);

        const phaseMaterial = [materials.phaseA, materials.phaseC, materials.phaseB][slot % 3];
        const coilAssembly = new THREE.Group();
        coilAssembly.add(
          new THREE.Mesh(concentratedCoil.linerGeometry, materials.liner),
          new THREE.Mesh(concentratedCoil.geometry, phaseMaterial),
        );
        coilAssembly.scale.setScalar(VISUAL_SCALE);
        coilAssembly.rotation.z = THREE.MathUtils.degToRad(angleDeg);
        motorGroup.add(coilAssembly);
      }

      const coreGeo = new THREE.CylinderGeometry(MAGNET_IN_R - 0.2, MAGNET_IN_R - 0.2, STACK, 96);
      coreGeo.rotateX(Math.PI / 2);
      const bearingWidth = STACK * 0.13;
      const bearingZ = STACK / 2 + bearingWidth + STACK * 0.115 / 2;
      const bearingOuterZ = bearingZ + bearingWidth / 2;
      const originalShaftLength = STACK * 1.83;
      const originalShaftCenterZ = STACK * 0.11;
      const originalShaftFrontZ = originalShaftCenterZ + originalShaftLength / 2;
      const originalShaftRearZ = originalShaftCenterZ - originalShaftLength / 2;
      const shaftFrontZ = bearingOuterZ
        + (originalShaftFrontZ - bearingOuterZ) * SHAFT_OVERHANG_SCALE;
      const shaftRearZ = -bearingOuterZ
        - (-bearingOuterZ - originalShaftRearZ) * SHAFT_OVERHANG_SCALE;
      const shaftLength = shaftFrontZ - shaftRearZ;
      const shaftCenterZ = (shaftFrontZ + shaftRearZ) / 2;
      const shaftGeo = new THREE.CylinderGeometry(SHAFT_R, SHAFT_R, shaftLength, 48);
      shaftGeo.rotateX(Math.PI / 2);
      shaftGeo.translate(0, 0, shaftCenterZ);
      addPart(coreGeo, materials.rotor, 0x94a3b8, rotorGroup, wireRotorGroup);
      addPart(shaftGeo, materials.shaft, 0x64748b, rotorGroup, wireRotorGroup);
      const shaftKeyLength = Math.max(1.2, shaftFrontZ - bearingOuterZ - 0.5);
      const shaftKeyGeo = new THREE.BoxGeometry(SHAFT_R * 0.52, SHAFT_R * 0.18, shaftKeyLength);
      shaftKeyGeo.translate(
        SHAFT_R * 0.94,
        0,
        bearingOuterZ + 0.25 + shaftKeyLength / 2,
      );
      rotorGroup.add(new THREE.Mesh(shaftKeyGeo, materials.shaftKey));

      const magnetHalfSpanDeg = THREE.MathUtils.radToDeg(15.7 / (MAGNET_IN_R + MAGNET_OUT_R));
      const magnetSplitRadius = (MAGNET_IN_R + MAGNET_OUT_R) / 2;
      const magnetAirgapGeo = magnetGeometry(magnetSplitRadius, MAGNET_OUT_R, magnetHalfSpanDeg);
      const magnetRotorGeo = magnetGeometry(MAGNET_IN_R, magnetSplitRadius, magnetHalfSpanDeg);
      for (let pole = 0; pole < POLES; pole += 1) {
        const isNorth = pole % 2 === 0;
        const magnetUnit = new THREE.Group();
        magnetUnit.add(
          new THREE.Mesh(magnetAirgapGeo, isNorth ? materials.magN : materials.magS),
          new THREE.Mesh(magnetRotorGeo, isNorth ? materials.oppositeS : materials.oppositeN),
        );
        magnetUnit.rotation.z = (pole * Math.PI * 2) / POLES;
        rotorGroup.add(magnetUnit);
        const magnetAirgapEdges = new THREE.LineSegments(
          new THREE.EdgesGeometry(magnetAirgapGeo, 18),
          wire(isNorth ? DESIGN_MAGNET_N_FILL : DESIGN_MAGNET_S_FILL),
        );
        const magnetRotorEdges = new THREE.LineSegments(
          new THREE.EdgesGeometry(magnetRotorGeo, 18),
          wire(isNorth ? DESIGN_MAGNET_S_FILL : DESIGN_MAGNET_N_FILL),
        );
        (magnetAirgapEdges.material as THREE.Material).userData.landingPart = 'magnets';
        (magnetRotorEdges.material as THREE.Material).userData.landingPart = 'magnets';
        magnetAirgapEdges.rotation.z = magnetUnit.rotation.z;
        magnetRotorEdges.rotation.z = magnetUnit.rotation.z;
        wireRotorGroup.add(magnetAirgapEdges, magnetRotorEdges);

        const labelAngle = magnetUnit.rotation.z + Math.PI / 2;
        const labelRadius = (MAGNET_IN_R + MAGNET_OUT_R) / 2;
        const label = makePoleLabel(
          isNorth ? 'N' : 'S',
          isNorth ? DESIGN_MAGNET_N_FILL : DESIGN_MAGNET_S_FILL,
        );
        label.position.set(
          Math.cos(labelAngle) * labelRadius,
          Math.sin(labelAngle) * labelRadius,
          STACK / 2 + 0.55,
        );
        rotorGroup.add(label);
      }

      const sleeveGeo = new THREE.CylinderGeometry(MAGNET_OUT_R + 0.22, MAGNET_OUT_R + 0.22, STACK * 1.015, 96, 1, true);
      sleeveGeo.rotateX(Math.PI / 2);
      rotorGroup.add(new THREE.Mesh(sleeveGeo, materials.sleeve));

      // Keep the bearings from the current product viewer, but omit the end
      // caps so the landing hero still exposes the electromagnetic assembly.
      const buildLandingBearing = (z: number) => {
        const group = new THREE.Group();
        const boreRadius = SHAFT_R;
        const outerRadius = HUB_R;
        const width = bearingWidth;
        const radialBuild = outerRadius - boreRadius;
        const innerRaceOuter = boreRadius + radialBuild * 0.34;
        const outerRaceInner = boreRadius + radialBuild * 0.76;
        const ballPitch = (innerRaceOuter + outerRaceInner) / 2;
        const ballRadius = Math.max(0.2, (outerRaceInner - innerRaceOuter) * 0.62);

        group.add(
          new THREE.Mesh(extrude(ringShape(innerRaceOuter, boreRadius), width), materials.bearingRace),
          new THREE.Mesh(extrude(ringShape(outerRadius, outerRaceInner), width), materials.bearingRace),
          new THREE.Mesh(
            extrude(ringShape(ballPitch + ballRadius * 0.42, ballPitch - ballRadius * 0.42), width * 0.42),
            materials.bearingCage,
          ),
        );
        const ballGeometry = new THREE.SphereGeometry(ballRadius, 20, 14);
        for (let index = 0; index < 9; index += 1) {
          const angle = (index / 9) * Math.PI * 2;
          const ball = new THREE.Mesh(ballGeometry, materials.bearingBall);
          ball.position.set(ballPitch * Math.cos(angle), ballPitch * Math.sin(angle), 0);
          group.add(ball);
        }
        group.position.z = z;
        return group;
      };
      rotorGroup.add(buildLandingBearing(bearingZ), buildLandingBearing(-bearingZ));

      const laminationMaterial = new THREE.MeshBasicMaterial({
        map: makeLaminationTexture(),
        transparent: true,
        opacity: 0.14,
        depthWrite: false,
      });
      laminationMaterial.userData.baseOpacity = 0.14;
      laminationMaterial.userData.fieldOpacityScale = 0.38;
      laminationMaterial.userData.landingPart = 'stator';
      solidMats.push(laminationMaterial);
      const laminationShell = new THREE.Mesh(
        new THREE.CylinderGeometry(STATOR_OD_R + 0.04, STATOR_OD_R + 0.04, STACK, 128, 1, true),
        laminationMaterial,
      );
      laminationShell.rotation.x = Math.PI / 2;
      motorGroup.add(laminationShell);

      const airgapMaterial = new THREE.MeshBasicMaterial({
        color: 0x72c7ff,
        transparent: true,
        opacity: 0.12,
        side: THREE.DoubleSide,
        depthWrite: false,
      });
      airgapMaterial.userData.baseOpacity = 0.28;
      airgapMaterial.userData.landingPart = 'airgap';
      airgapMats.push(airgapMaterial);
      const airgapEdgeMaterial = new THREE.MeshBasicMaterial({
        color: 0x3b82f6,
        transparent: true,
        opacity: 0.44,
        depthWrite: false,
      });
      airgapEdgeMaterial.userData.baseOpacity = 0.72;
      airgapEdgeMaterial.userData.landingPart = 'airgap';
      airgapMats.push(airgapEdgeMaterial);
      const airgapCylinder = new THREE.Mesh(
        new THREE.CylinderGeometry(29.75, 29.75, STACK * 1.025, 96, 1, true),
        airgapMaterial,
      );
      airgapCylinder.rotation.x = Math.PI / 2;
      const airgapEdge = new THREE.Mesh(new THREE.TorusGeometry(29.75, 0.16, 8, 128), airgapEdgeMaterial);
      airgapEdge.position.z = STACK / 2 + 0.35;
      motorGroup.add(airgapCylinder, airgapEdge, rotorGroup);
      wireGroup.add(wireRotorGroup);
      wireGroup.visible = false;

      const decodeBase64 = (base64: string) => {
        const binary = window.atob(base64);
        const bytes = new Uint8Array(binary.length);
        for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
        return bytes;
      };
      let updateSolvedFieldPlayback = (rotorAngleRad: number) => {
        void rotorAngleRad;
      };
      const markAssetLoadError = () => {
        if (cancelled) return;
        setLoadError(true);
        setActiveStep(0);
      };
      const loadJsonFixture = async <Fixture,>(url: URL) => {
        const response = await window.fetch(url);
        if (!response.ok) throw new Error(`landing preview asset failed with ${response.status}`);
        return response.json() as Promise<Fixture>;
      };

      let meshAssetsPromise: Promise<void> | null = null;
      const ensureMeshAssets = () => {
        if (meshAssetsPromise) return meshAssetsPromise;
        meshAssetsPromise = loadJsonFixture<MeshFixture>(
          new URL('./hero_mesh_8p12s.compact.json', import.meta.url),
        )
          .then((meshFixture) => {
            if (cancelled) return;
            const coordinates = new Int16Array(decodeBase64(meshFixture.coordinates).buffer);
            const edgeIndices = new Uint16Array(decodeBase64(meshFixture.edgeIndices).buffer);
            const fixtureScale = meshFixture.coordinateScale * STATOR_OD_R / meshFixture.outerRadius;
            const statorMeshVertices: number[] = [];
            const rotorMeshVertices: number[] = [];
            const meshZ = STACK / 2 + 0.72;
            const rotorMeshRadius = MAGNET_OUT_R + 0.16;
            for (let index = 0; index < edgeIndices.length; index += 2) {
              const firstSourceOffset = edgeIndices[index] * 2;
              const secondSourceOffset = edgeIndices[index + 1] * 2;
              const x1 = coordinates[firstSourceOffset] * fixtureScale;
              const y1 = coordinates[firstSourceOffset + 1] * fixtureScale;
              const x2 = coordinates[secondSourceOffset] * fixtureScale;
              const y2 = coordinates[secondSourceOffset + 1] * fixtureScale;
              const isRotorEdge = Math.max(Math.hypot(x1, y1), Math.hypot(x2, y2)) <= rotorMeshRadius;
              const targetVertices = isRotorEdge ? rotorMeshVertices : statorMeshVertices;
              targetVertices.push(x1, y1, meshZ, x2, y2, meshZ);
            }
            const meshLineMaterial = new THREE.LineBasicMaterial({
              color: 0xcbd5e1,
              transparent: true,
              opacity: 0,
              depthTest: false,
              depthWrite: false,
              toneMapped: false,
            });
            meshLineMaterial.userData.baseOpacity = 1;
            meshMats.push(meshLineMaterial);
            const createMeshEdges = (vertices: number[]) => {
              const geometry = new THREE.BufferGeometry();
              geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
              const edges = new THREE.LineSegments(geometry, meshLineMaterial);
              edges.renderOrder = 11;
              meshLineObjects.push(edges);
              return edges;
            };
            femGroup.add(createMeshEdges(statorMeshVertices));
            rotorFemGroup.add(createMeshEdges(rotorMeshVertices));
          })
          .catch(markAssetLoadError);
        return meshAssetsPromise;
      };

      let fieldAssetsPromise: Promise<void> | null = null;
      const ensureFieldAssets = () => {
        if (fieldAssetsPromise) return fieldAssetsPromise;
        fieldAssetsPromise = Promise.all([
          loadJsonFixture<FieldFixture>(new URL('./hero_field_8p12s.compact.json', import.meta.url)),
          loadJsonFixture<HeatmapFixture>(new URL('./hero_b_heatmap_8p12s.compact.json', import.meta.url)),
        ])
          .then(([solvedFieldFixture, solvedHeatmapFixture]) => {
            if (cancelled) return;

            // The heatmap is generated from the same solved sweep as the contours.
            // Two texture planes crossfade between adjacent mechanical-angle frames,
            // so |B|, orange field lines, and rotor motion share one playback clock.
            if (
              solvedHeatmapFixture.schemaVersion !== 'coilem.landing_b_heatmap.v2'
              || solvedHeatmapFixture.frames.length !== solvedFieldFixture.frames.length
              || Math.abs(solvedHeatmapFixture.slotPeriodMechanicalDeg - solvedFieldFixture.slotPeriodMechanicalDeg) > 1e-6
              || Math.abs(solvedHeatmapFixture.frameStepMechanicalDeg - solvedFieldFixture.frameStepMechanicalDeg) > 1e-6
            ) {
              throw new Error('landing heatmap playback does not match the solved field sweep');
            }
            const paletteLut = new Uint8Array(256 * 3);
            for (let value = 0; value < 256; value += 1) {
              const palettePosition = (value / 255) * (SOLVED_HEATMAP_PALETTE.length - 1);
              const paletteStart = Math.min(SOLVED_HEATMAP_PALETTE.length - 1, Math.floor(palettePosition));
              const paletteEnd = Math.min(SOLVED_HEATMAP_PALETTE.length - 1, paletteStart + 1);
              const blend = palettePosition - paletteStart;
              const start = SOLVED_HEATMAP_PALETTE[paletteStart];
              const end = SOLVED_HEATMAP_PALETTE[paletteEnd];
              for (let channel = 0; channel < 3; channel += 1) {
                const shift = (2 - channel) * 8;
                const startChannel = (start >> shift) & 0xff;
                const endChannel = (end >> shift) & 0xff;
                paletteLut[value * 3 + channel] = Math.round(startChannel + (endChannel - startChannel) * blend);
              }
            }
            const heatmapTextures = solvedHeatmapFixture.frames.map((frame) => {
              const values = decodeBase64(frame.values);
              const expectedLength = solvedHeatmapFixture.width * solvedHeatmapFixture.height;
              if (values.length !== expectedLength) {
                throw new Error('landing heatmap frame has an invalid raster size');
              }
              const pixels = new Uint8Array(expectedLength * 4);
              for (let pixel = 0; pixel < expectedLength; pixel += 1) {
                const x = ((pixel % solvedHeatmapFixture.width) + 0.5) / solvedHeatmapFixture.width * 2 - 1;
                const y = (Math.floor(pixel / solvedHeatmapFixture.width) + 0.5) / solvedHeatmapFixture.height * 2 - 1;
                const radius = Math.hypot(x, y);
                const alpha = radius <= 0.985 ? 255 : radius >= 1 ? 0 : Math.round((1 - radius) / 0.015 * 255);
                const value = values[pixel];
                const target = pixel * 4;
                pixels[target] = paletteLut[value * 3];
                pixels[target + 1] = paletteLut[value * 3 + 1];
                pixels[target + 2] = paletteLut[value * 3 + 2];
                pixels[target + 3] = alpha;
              }
              const texture = new THREE.DataTexture(
                pixels,
                solvedHeatmapFixture.width,
                solvedHeatmapFixture.height,
                THREE.RGBAFormat,
                THREE.UnsignedByteType,
              );
              texture.colorSpace = THREE.SRGBColorSpace;
              // Rows are already emitted in the same reflected-Y orientation as the
              // contour geometry, so playback remains consistent across WebGL backends.
              texture.flipY = false;
              texture.magFilter = THREE.LinearFilter;
              texture.minFilter = THREE.LinearFilter;
              texture.generateMipmaps = false;
              texture.needsUpdate = true;
              textures.push(texture);
              return texture;
            });
            const heatmapZ = STACK / 2 + 1.02;
            const heatmapGeometry = new THREE.PlaneGeometry(
              solvedHeatmapFixture.extentRadius * 2,
              solvedHeatmapFixture.extentRadius * 2,
            );
            for (let index = 0; index < 2; index += 1) {
              const material = new THREE.MeshBasicMaterial({
                map: heatmapTextures[0],
                transparent: true,
                opacity: 0,
                side: THREE.DoubleSide,
                depthTest: false,
                depthWrite: false,
                toneMapped: false,
              });
              material.userData.baseOpacity = 0.46;
              material.userData.frameWeight = 0;
              material.userData.frameIndex = 0;
              heatmapMats.push(material);
              const mesh = new THREE.Mesh(heatmapGeometry, material);
              mesh.position.z = heatmapZ;
              mesh.renderOrder = 8;
              heatmapFrameMeshes.push(mesh);
              heatmapGroup.add(mesh);
            }

            const zFront = STACK / 2 + 1.32;
            const fieldLineColor = new THREE.Color(SOLVED_FIELD_LINE_COLOR);
            solvedFieldFixture.frames.forEach((fieldFrame) => {
              const positions: number[] = [];
              const colors: number[] = [];
              fieldFrame.levels.forEach((polylines) => {
                polylines.forEach((polyline) => {
                  for (let pointIndex = 1; pointIndex < polyline.length; pointIndex += 1) {
                    const [x1, y1] = polyline[pointIndex - 1];
                    const [x2, y2] = polyline[pointIndex];
                    positions.push(
                      x1 * solvedFieldFixture.coordinateScale,
                      -y1 * solvedFieldFixture.coordinateScale,
                      zFront,
                      x2 * solvedFieldFixture.coordinateScale,
                      -y2 * solvedFieldFixture.coordinateScale,
                      zFront,
                    );
                    colors.push(
                      fieldLineColor.r,
                      fieldLineColor.g,
                      fieldLineColor.b,
                      fieldLineColor.r,
                      fieldLineColor.g,
                      fieldLineColor.b,
                    );
                  }
                });
              });
              const geometry = new THREE.BufferGeometry();
              geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
              geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
              const material = new THREE.LineBasicMaterial({
                vertexColors: true,
                transparent: true,
                opacity: 0,
                blending: THREE.NormalBlending,
                depthTest: false,
                depthWrite: false,
              });
              material.userData.frameWeight = 0;
              material.userData.baseOpacity = 0.9;
              fieldFrameMaterials.push(material);
              const lines = new THREE.LineSegments(geometry, material);
              lines.visible = false;
              lines.renderOrder = 10;
              fieldFrameMeshes.push(lines);
              fluxGroup.add(lines);
            });

            updateSolvedFieldPlayback = (rotorAngleRad: number) => {
              const periodDeg = solvedFieldFixture.slotPeriodMechanicalDeg;
              // The rotor, field contours, and |B| heatmap all represent the same
              // solved mechanical angle. Keep them on one playback clock so the
              // raster cannot counter-rotate relative to the magnets.
              const solvedPlayback = resolveLandingSolvedPlayback(
                rotorAngleRad,
                periodDeg,
                solvedFieldFixture.frameStepMechanicalDeg,
                solvedFieldFixture.frames.length,
              );
              fluxGroup.rotation.z = -THREE.MathUtils.degToRad(solvedPlayback.rigidSectorDeg);
              heatmapGroup.rotation.z = -THREE.MathUtils.degToRad(solvedPlayback.rigidSectorDeg);
              [solvedPlayback.frameA, solvedPlayback.frameB].forEach((frameIndex, layerIndex) => {
                const material = heatmapMats[layerIndex];
                if (material.userData.frameIndex !== frameIndex) {
                  material.map = heatmapTextures[frameIndex];
                  material.userData.frameIndex = frameIndex;
                  material.needsUpdate = true;
                }
                material.userData.frameWeight = layerIndex === 0
                  ? 1 - solvedPlayback.blend
                  : solvedPlayback.blend;
                heatmapFrameMeshes[layerIndex].rotation.z = 0;
              });
              fieldFrameMaterials.forEach((material, index) => {
                material.userData.frameWeight = index === solvedPlayback.frameA
                  ? 1 - solvedPlayback.blend
                  : index === solvedPlayback.frameB
                    ? solvedPlayback.blend
                    : 0;
                fieldFrameMeshes[index].rotation.z = 0;
              });
              if (solvedPlayback.frameB === 0 && solvedPlayback.blend > 0) {
                fieldFrameMeshes[solvedPlayback.frameB].rotation.z = -THREE.MathUtils.degToRad(periodDeg);
              }
              if (solvedPlayback.frameB === 0 && solvedPlayback.blend > 0) {
                heatmapFrameMeshes[1].rotation.z = -THREE.MathUtils.degToRad(periodDeg);
              }
            };
            updateSolvedFieldPlayback(rotorGroup.rotation.z);
          })
          .catch(markAssetLoadError);
        return fieldAssetsPromise;
      };

      motorGroup.add(heatmapGroup, fluxGroup);
      assetLoaderRef.current = {
        mesh: () => { void ensureMeshAssets(); },
        field: () => { void ensureFieldAssets(); },
      };
      if (activeStepRef.current === 1) void ensureMeshAssets();
      if (activeStepRef.current === 2) void ensureFieldAssets();

      scene.add(motorGroup, wireGroup, femGroup);
      sceneStateRef.current = { rotorGroup, wireRotorGroup };
      const explodeTargets: Array<{
        object: THREE.Object3D;
        baseZ: number;
        targetOffsetZ: number;
        phaseStart: number;
        phaseEnd: number;
      }> = [];
      const registerExplodeTargets = (root: THREE.Object3D) => {
        root.traverse((object) => {
          if (!('material' in object)) return;
          const objectMaterial = object.material as THREE.Material | THREE.Material[];
          const partId = (Array.isArray(objectMaterial) ? objectMaterial : [objectMaterial])
            .map((material) => material.userData.landingPart as LandingPartId | undefined)
            .find(Boolean);
          if (!partId) return;
          let targetOffsetZ = 0;
          // Full explode uses non-overlapping axial stations with a small gap.
          // The windings live in a 0.5-scale parent, so their local offset is
          // doubled to preserve the intended world-space station.
          if (partId === 'stator') targetOffsetZ = 215;
          if (partId === 'windings') targetOffsetZ = 320;
          if (partId === 'airgap') targetOffsetZ = 105;
          if (partId === 'magnets') targetOffsetZ = 50;
          if (partId === 'rotor') targetOffsetZ = -5;
          if (partId === 'shaft') targetOffsetZ = -101.5;
          if (partId === 'bearings') {
            let ancestor: THREE.Object3D | null = object.parent;
            while (ancestor && Math.abs(ancestor.position.z) < 0.01) ancestor = ancestor.parent;
            targetOffsetZ = (ancestor?.position.z ?? 1) >= 0 ? -72.375 : -14.625;
          }
          if (targetOffsetZ !== 0) {
            const [phaseStart, phaseEnd] = EXPLODE_PHASES[partId];
            explodeTargets.push({
              object,
              baseZ: object.position.z,
              targetOffsetZ,
              phaseStart,
              phaseEnd,
            });
          }
        });
      };
      registerExplodeTargets(motorGroup);
      registerExplodeTargets(wireGroup);

      const resize = () => {
        const width = stage.clientWidth;
        const height = stage.clientHeight;
        if (width <= 0 || height <= 0) return;
        renderer.setSize(width, height, false);
        camera.aspect = width / height;
        camera.updateProjectionMatrix();
      };
      const resizeObserver = new ResizeObserver(resize);
      resizeObserver.observe(stage);
      resize();

      const lerp = (current: number, target: number, factor: number) => current + (target - current) * factor;
      const timer = new THREE.Timer();
      timer.connect(document);
      let idleOrbitDirection = 1;
      let animationFrame = 0;
      let isStageVisible = true;
      const materialVisibilityScale = (material: THREE.Material) => {
        const partId = material.userData.landingPart as LandingPartId | undefined;
        if (!partId) return 1;
        const activeMode = PREVIEW_MODES[activeStepRef.current];
        return partVisibilityRef.current[partId] && !MODE_HIDDEN_PARTS[activeMode].includes(partId) ? 1 : 0;
      };
      const applyMaterialVisibility = (material: THREE.Material) => {
        const visibilityScale = materialVisibilityScale(material);
        // Opacity alone does not stop a transparent Three.js material from
        // writing to the depth buffer and masking components behind it.
        material.visible = visibilityScale > 0;
        return visibilityScale;
      };
      const renderFrame = (timestamp?: number) => {
        animationFrame = 0;
        if (!isStageVisible || document.visibilityState !== 'visible') return;
        animationFrame = window.requestAnimationFrame(renderFrame);
        timer.update(timestamp);
        const deltaSeconds = Math.min(timer.getDelta(), 0.04);
        const target = VIEW_STATES[activeStepRef.current];
        solidMats.forEach((material) => {
          const visibilityScale = applyMaterialVisibility(material);
          const fieldOpacityScale = activeStepRef.current === 2
            ? (material.userData.fieldOpacityScale ?? 1)
            : 1;
          material.opacity = lerp(
            material.opacity,
            target.solid
              * (material.userData.baseOpacity ?? 1)
              * fieldOpacityScale
              * visibilityScale,
            0.1,
          );
        });
        wireMats.forEach((material) => {
          const visibilityScale = applyMaterialVisibility(material);
          material.opacity = lerp(
            material.opacity,
            target.wire * (material.userData.baseOpacity ?? 1) * visibilityScale,
            0.1,
          );
        });
        meshMats.forEach((material) => {
          material.opacity = lerp(material.opacity, target.mesh * (material.userData.baseOpacity ?? 1), 0.1);
        });
        meshLineObjects.forEach((edges) => {
          edges.renderOrder = activeStepRef.current === 2 ? 7 : 11;
        });
        airgapMats.forEach((material) => {
          const visibilityScale = applyMaterialVisibility(material);
          material.opacity = lerp(
            material.opacity,
            target.airgap * (material.userData.baseOpacity ?? 1) * visibilityScale,
            0.1,
          );
        });
        labelMats.forEach((material) => {
          const visibilityScale = applyMaterialVisibility(material);
          material.opacity = lerp(material.opacity, target.labels * visibilityScale, 0.1);
        });
        wireGroup.visible = wireMats.some((material) => material.visible && material.opacity > 0.02);
        femGroup.visible = (meshMats[0]?.opacity ?? 0) > 0.02;

        if (!reducedMotion) {
          rotorGroup.rotation.z -= ROTOR_SPIN_RADIANS_PER_SECOND * deltaSeconds;
        }
        wireRotorGroup.rotation.z = rotorGroup.rotation.z;
        rotorFemGroup.rotation.z = rotorGroup.rotation.z;
        updateSolvedFieldPlayback(rotorGroup.rotation.z);
        fieldFrameMaterials.forEach((material, index) => {
          const frameOpacity = target.flux * material.userData.baseOpacity * material.userData.frameWeight;
          material.opacity = lerp(material.opacity, frameOpacity, 0.18);
          fieldFrameMeshes[index].visible = material.opacity > 0.008 || material.userData.frameWeight > 0;
        });
        heatmapMats.forEach((material, index) => {
          const frameOpacity = target.heatmap * material.userData.baseOpacity * material.userData.frameWeight;
          material.opacity = lerp(material.opacity, frameOpacity, 0.18);
          heatmapFrameMeshes[index].visible = material.opacity > 0.008 || material.userData.frameWeight > 0;
        });
        const explodeProgress = (immersiveRef.current ? explodeAmountRef.current : 0) / 100;
        explodeTargets.forEach(({ object, baseZ, targetOffsetZ, phaseStart, phaseEnd }) => {
          const phaseProgress = THREE.MathUtils.clamp(
            (explodeProgress - phaseStart) / (phaseEnd - phaseStart),
            0,
            1,
          );
          object.position.z = lerp(object.position.z, baseZ + phaseProgress * targetOffsetZ, 0.14);
        });
        const explodedAssemblyScale = 1 - explodeProgress * 0.58;
        const assemblyScale = lerp(motorGroup.scale.x, explodedAssemblyScale, 0.14);
        motorGroup.scale.setScalar(assemblyScale);
        wireGroup.scale.setScalar(assemblyScale);
        const explodedSceneOffsetZ = lerp(
          motorGroup.position.z,
          EXPLODED_SCENE_OFFSET_Z * explodeProgress,
          0.14,
        );
        motorGroup.position.z = explodedSceneOffsetZ;
        wireGroup.position.z = explodedSceneOffsetZ;
        const analysisLayerProgress = THREE.MathUtils.clamp(
          explodeProgress / EXPLODE_PHASES.stator[1],
          0,
          1,
        );
        const analysisLayerOffsetZ = lerp(
          heatmapGroup.position.z,
          ANALYSIS_LAYER_EXPLODED_OFFSET_Z * analysisLayerProgress,
          0.14,
        );
        // Mesh mode and Field mode share one front-most axial station. The
        // FEM mesh is scene-level, so mirror the motor assembly's scale and
        // convert the child-local offset into world space.
        heatmapGroup.position.z = analysisLayerOffsetZ;
        fluxGroup.position.z = analysisLayerOffsetZ;
        femGroup.position.z = explodedSceneOffsetZ + analysisLayerOffsetZ * assemblyScale;
        femGroup.scale.setScalar(assemblyScale);
        controls.maxDistance = immersiveRef.current && stage.clientHeight > stage.clientWidth
          ? IMMERSIVE_PORTRAIT_MAX_DISTANCE
          : 280;
        controls.minAzimuthAngle = immersiveRef.current ? -Infinity : -IDLE_ORBIT_LIMIT_RAD;
        controls.maxAzimuthAngle = immersiveRef.current ? Infinity : IDLE_ORBIT_LIMIT_RAD;
        controls.autoRotate = !reducedMotion && !immersiveRef.current;
        if (controls.autoRotate) {
          const azimuthAngle = controls.getAzimuthalAngle();
          if (azimuthAngle <= controls.minAzimuthAngle + IDLE_ORBIT_EDGE_EPSILON_RAD) {
            idleOrbitDirection = -1;
          } else if (azimuthAngle >= controls.maxAzimuthAngle - IDLE_ORBIT_EDGE_EPSILON_RAD) {
            idleOrbitDirection = 1;
          }
          controls.autoRotateSpeed = IDLE_ORBIT_SPEED * idleOrbitDirection;
        }
        controls.update(deltaSeconds);
        renderer.render(scene, camera);
      };
      const resumeRendering = () => {
        if (animationFrame || !isStageVisible || document.visibilityState !== 'visible') return;
        animationFrame = window.requestAnimationFrame(renderFrame);
      };
      const visibilityObserver = new IntersectionObserver(([entry]) => {
        isStageVisible = entry?.isIntersecting ?? false;
        if (isStageVisible) {
          resumeRendering();
        } else if (animationFrame) {
          window.cancelAnimationFrame(animationFrame);
          animationFrame = 0;
        }
      }, { rootMargin: '120px' });
      const handleVisibilityChange = () => {
        if (document.visibilityState === 'visible') {
          resumeRendering();
        } else if (animationFrame) {
          window.cancelAnimationFrame(animationFrame);
          animationFrame = 0;
        }
      };
      visibilityObserver.observe(stage);
      document.addEventListener('visibilitychange', handleVisibilityChange);
      resumeRendering();

      disposeScene = () => {
        if (animationFrame) window.cancelAnimationFrame(animationFrame);
        visibilityObserver.disconnect();
        document.removeEventListener('visibilitychange', handleVisibilityChange);
        resizeObserver.disconnect();
        controls.dispose();
        timer.dispose();
        assetLoaderRef.current = null;
        sceneStateRef.current = null;
        const geometries = new Set<THREE.BufferGeometry>();
        const sceneMaterials = new Set<THREE.Material>();
        scene.traverse((object) => {
          if ('geometry' in object && object.geometry instanceof THREE.BufferGeometry) geometries.add(object.geometry);
          if ('material' in object) {
            const objectMaterial = object.material as THREE.Material | THREE.Material[];
            (Array.isArray(objectMaterial) ? objectMaterial : [objectMaterial]).forEach((material) => sceneMaterials.add(material));
          }
        });
        geometries.forEach((geometry) => geometry.dispose());
        sceneMaterials.forEach((material) => material.dispose());
        textures.forEach((texture) => texture.dispose());
        environmentTarget.dispose();
        pmrem.dispose();
        renderer.dispose();
      };
    };

    initialize().catch(() => {
      if (!cancelled) {
        setLoadError(true);
        setActiveStep(0);
      }
    });

    return () => {
      cancelled = true;
      disposeScene();
    };
  }, []);

  return (
    <div
      className={`landing-3d-preview${isImmersive ? ' is-immersive' : ''}`}
      role={isImmersive ? 'dialog' : undefined}
      aria-modal={isImmersive || undefined}
      aria-label="Interactive 8 pole 12 slot SPM motor preview"
    >
      <div className="landing-3d-model-label">200 MM · 8P/12S SPM</div>
      <div className="landing-3d-body">
        <div
          ref={stageRef}
          className="landing-3d-stage"
          onDoubleClick={handleStageDoubleClick}
          onPointerDown={handleStagePointerDown}
          onPointerUp={handleStagePointerUp}
          onPointerCancel={() => { touchStartRef.current = null; }}
        >
          <canvas ref={canvasRef} aria-hidden="true" />
          {loadError && <div className="landing-3d-error">3D preview unavailable</div>}
          <button
            ref={fullscreenButtonRef}
            type="button"
            className="landing-fullscreen-button"
            aria-label={isImmersive ? 'Exit fullscreen motor view' : 'Open fullscreen motor view'}
            aria-keyshortcuts={isImmersive ? 'Escape' : undefined}
            title={isImmersive ? 'Exit fullscreen' : 'View motor fullscreen'}
            onPointerDown={(event) => event.stopPropagation()}
            onPointerUp={(event) => event.stopPropagation()}
            onClick={toggleImmersive}
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              {isImmersive ? (
                <path d="M9 3v6H3M15 3v6h6M9 21v-6H3M15 21v-6h6" />
              ) : (
                <path d="M9 3H3v6M15 3h6v6M9 21H3v-6M15 21h6v-6" />
              )}
            </svg>
          </button>
          {isImmersive && (
            <label
              className="landing-explode-control"
              onPointerDown={(event) => event.stopPropagation()}
              onPointerUp={(event) => event.stopPropagation()}
              onDoubleClick={(event) => event.stopPropagation()}
            >
              <span>Explode</span>
              <input
                type="range"
                min="0"
                max="100"
                step="1"
                value={explodeAmount}
                aria-label="Explode motor assembly"
                onChange={(event) => setExplodeAmount(Number(event.target.value))}
              />
              <output>{explodeAmount}%</output>
            </label>
          )}
          <div
            className="landing-part-visibility-control"
            role="group"
            aria-label="Motor component visibility"
            onPointerDown={(event) => event.stopPropagation()}
            onPointerUp={(event) => event.stopPropagation()}
            onPointerCancel={(event) => event.stopPropagation()}
          >
            {LANDING_PARTS.map((part) => {
              const hiddenByMode = MODE_HIDDEN_PARTS[activeMode].includes(part.id);
              const visible = partVisibility[part.id] && !hiddenByMode;
              return (
                <button
                  key={part.id}
                  type="button"
                  className={visible ? 'is-visible' : ''}
                  aria-pressed={visible}
                  disabled={hiddenByMode}
                  title={hiddenByMode ? `${part.label} hidden in ${activeMode} view` : `Toggle ${part.label}`}
                  onClick={() => togglePart(part.id)}
                >
                  <span aria-hidden="true" />
                  {part.label}
                </button>
              );
            })}
          </div>
          <LandingPreviewModeControl
            activeMode={activeMode}
            ariaLabel="Motor preview view"
            onSelect={selectMode}
            disabledModes={loadError ? ['mesh', 'field'] : []}
          />
        </div>
      </div>
    </div>
  );
};
