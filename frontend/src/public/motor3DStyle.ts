import * as THREE from 'three';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import { PUBLIC_MOTOR_COLORS, renderTargetColor } from './motorPalette';

/** The same studio and exposure for parametric, imported and meshed motor geometry. */
export function addMotorStudioLighting(renderer: THREE.WebGLRenderer, scene: THREE.Scene, radius: number): () => void {
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.02;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;
  const room = new RoomEnvironment();
  const pmrem = new THREE.PMREMGenerator(renderer);
  const environment = pmrem.fromScene(room, 0.04);
  room.dispose();
  pmrem.dispose();
  scene.environment = environment.texture;
  scene.environmentIntensity = 0.62;

  scene.add(new THREE.AmbientLight(0xffe4c4, 0.30));
  scene.add(new THREE.HemisphereLight(0xffe2bd, 0x171310, 0.52));
  const key = new THREE.DirectionalLight(0xffdcae, 1.62);
  key.position.set(radius * 2, radius * 2.4, radius * 2.6);
  key.castShadow = true;
  key.shadow.mapSize.set(1_024, 1_024);
  key.shadow.camera.left = -radius * 2.4;
  key.shadow.camera.right = radius * 2.4;
  key.shadow.camera.top = radius * 2.4;
  key.shadow.camera.bottom = -radius * 2.4;
  key.shadow.camera.near = 1;
  key.shadow.camera.far = radius * 8;
  key.shadow.bias = -0.0001;
  key.shadow.normalBias = radius * 0.001;
  scene.add(key);
  const fill = new THREE.DirectionalLight(0xbcd4f0, 0.56);
  fill.position.set(-radius * 2.2, radius * 0.8, radius * 1.4);
  scene.add(fill);
  const rim = new THREE.DirectionalLight(0x67e8f9, 0.58);
  rim.position.set(-radius * 2, -radius, radius * 1.2);
  scene.add(rim);
  const warmRim = new THREE.DirectionalLight(0xffb347, 0.42);
  warmRim.position.set(radius * 0.8, -radius * 2.1, -radius);
  scene.add(warmRim);
  return () => {
    scene.environment = null;
    key.shadow.dispose();
    environment.dispose();
  };
}

/** Reflective lamination steel, with a restrained coat rather than a white glare. */
export function motorSteelMaterial(
  part: 'stator' | 'tooth' | 'rotor',
  overrides: THREE.MeshPhysicalMaterialParameters = {},
): THREE.MeshPhysicalMaterial {
  const finish = {
    stator: { color: renderTargetColor(PUBLIC_MOTOR_COLORS.statorSteel), metalness: .62, roughness: .47, clearcoat: .06, clearcoatRoughness: .45 },
    tooth: { color: renderTargetColor(PUBLIC_MOTOR_COLORS.statorTooth), metalness: .56, roughness: .48, clearcoat: .05, clearcoatRoughness: .45 },
    rotor: { color: 0x36465c, metalness: .68, roughness: .46, clearcoat: .05, clearcoatRoughness: .5 },
  }[part];
  return new THREE.MeshPhysicalMaterial({ ...finish, envMapIntensity: .55, ...overrides });
}

export function motorMagnetMaterial(polarity: 'N' | 'S'): THREE.MeshPhysicalMaterial {
  return new THREE.MeshPhysicalMaterial({
    color: renderTargetColor(polarity === 'N' ? PUBLIC_MOTOR_COLORS.magnetNorth : PUBLIC_MOTOR_COLORS.magnetSouth),
    emissive: polarity === 'N' ? 0x3d090c : 0x071d42,
    metalness: .2, roughness: .28, clearcoat: .26, clearcoatRoughness: .3,
  });
}

export function phaseMaterial(hex: string): THREE.MeshPhysicalMaterial {
  return new THREE.MeshPhysicalMaterial({
    color: renderTargetColor(hex), metalness: .08, roughness: .34, clearcoat: .2, clearcoatRoughness: .36,
  });
}
