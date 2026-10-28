import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

type Satellite = {
  mesh: THREE.Object3D;
  basePosition: THREE.Vector3;
  baseRotation: THREE.Quaternion;
  orbit: THREE.Quaternion;
  axis: THREE.Vector3;
  tier: 'middle' | 'outer';
  speed: number;
};

const CENTER = new THREE.Vector3(0, 0.54, 0);
const SHARED_AXIS = new THREE.Vector3(-1, 1, 0).normalize();
const TAU = Math.PI * 2;

export function CoreViewer({ mode = 'idle', onActivate }: { mode?: 'idle' | 'thinking' | 'speaking' | 'error'; onActivate?: () => void }) {
  const mount = useRef<HTMLDivElement>(null);
  const hold = useRef(false);
  const activation = useRef(onActivate);
  activation.current = onActivate;
    const modeRef = useRef(mode);
    modeRef.current = mode;
  const [status, setStatus] = useState('正在载入 3D 核心…');

  useEffect(() => {
    const host = mount.current;
    if (!host) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch {
      setStatus('此浏览器无法启动 3D 画面。');
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.55;
    host.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(35, 1, 0.01, 20);
    camera.position.set(0, 0.68, 2.45);
    camera.lookAt(CENTER);
    scene.add(new THREE.HemisphereLight(0xe8f4ff, 0x424052, 2.2));
    const key = new THREE.DirectionalLight(0xffffff, 3.2);
    key.position.set(-1.5, 2.5, 3);
    scene.add(key);
    const rim = new THREE.DirectionalLight(0x95baff, 2.5);
    rim.position.set(1.5, 1, -2);
    scene.add(rim);

    const resize = () => {
      const width = host.clientWidth || 320;
      const height = host.clientHeight || 340;
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.position.z = 2.45 * Math.max(1, Math.min(height / width, 1.45));
      camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(host);
    resize();

    const satellites: Satellite[] = [];
    const coreMeshes: THREE.Mesh[] = [];
    const modelMeshes: THREE.Mesh[] = [];
    let core: THREE.Object3D | undefined;
    let coreBase = new THREE.Quaternion();
    let disposed = false;
    let independent = false;
    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();

    void new GLTFLoader().loadAsync('/models/core_interactive_v9.glb').then((gltf) => {
      if (disposed) return;
      scene.add(gltf.scene);
      scene.updateMatrixWorld(true);
      const pieces = [...gltf.scene.children];
      for (const piece of pieces) {
        scene.attach(piece);
        piece.traverse((node) => {
          if (node instanceof THREE.Mesh) {
            modelMeshes.push(node);
            if (piece.name === 'EnergyCore') coreMeshes.push(node);
          }
        });
        if (piece.name === 'EnergyCore') {
          core = piece;
          coreBase = piece.quaternion.clone();
          continue;
        }
        const tier = piece.name.startsWith('MiddleShard_') ? 'middle' : piece.name.startsWith('OuterShard_') ? 'outer' : null;
        if (!tier) continue;
        const index = Number(piece.name.split('_')[1]);
        const variation = tier === 'outer' ? 0.45 : 0.32;
        const axis = SHARED_AXIS.clone().add(new THREE.Vector3(
          Math.sin(index * 2.39 + (tier === 'outer' ? 1 : 0)) * variation,
          Math.cos(index * 1.71) * variation * 0.5,
          Math.sin(index * 1.17) * variation,
        )).normalize();
        satellites.push({
          mesh: piece,
          basePosition: piece.position.clone(),
          baseRotation: piece.quaternion.clone(),
          orbit: new THREE.Quaternion(),
          axis,
          tier,
          speed: (tier === 'middle' ? TAU / 6 : -TAU / 8) * (2.3 + (index % 7) * 0.07),
        });
      }
      if (core && satellites.length === 74) setStatus('按住紫色核心，观察 74 块装甲分别升轨；松开后缓慢归位。');
      else setStatus('模型结构不完整，请检查 3D 文件。');
    }).catch(() => {
      if (!disposed) setStatus('3D 模型加载失败，请检查模型文件。');
    });

    let pressedAt = 0;
    let pressedOnModel = false;
    const onPointerDown = (event: PointerEvent) => {
      if (!core || event.button !== 0) return;
      const bounds = renderer.domElement.getBoundingClientRect();
      pointer.set(((event.clientX - bounds.left) / bounds.width) * 2 - 1,
        -((event.clientY - bounds.top) / bounds.height) * 2 + 1);
      raycaster.setFromCamera(pointer, camera);
      if (raycaster.intersectObjects(modelMeshes, false).length === 0) return;
      pressedOnModel = true;
      pressedAt = performance.now();
      renderer.domElement.setPointerCapture(event.pointerId);
      if (raycaster.intersectObjects(coreMeshes, false).length > 0) {
        hold.current = true;
        independent = true;
        setStatus('加速中：每块装甲沿各自轨道旋转。');
      }
    };
    const onPointerUp = (event: PointerEvent) => {
      if (!pressedOnModel) return;
      pressedOnModel = false;
      if (hold.current) {
        hold.current = false;
        setStatus('正在减速并回归常规轨道。');
      }
      if (event.type === 'pointerup' && performance.now() - pressedAt < 350) activation.current?.();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      event.preventDefault();
      if (event.repeat) return;
      activation.current?.();
    };
    renderer.domElement.addEventListener('pointerdown', onPointerDown);
    renderer.domElement.addEventListener('pointerup', onPointerUp);
    renderer.domElement.addEventListener('pointercancel', onPointerUp);
    renderer.domElement.addEventListener('lostpointercapture', onPointerUp);
    window.addEventListener('pointerup', onPointerUp);
    host.addEventListener('keydown', onKeyDown);

    const clock = new THREE.Clock();
    const normalMiddle = new THREE.Quaternion();
    const normalOuter = new THREE.Quaternion();
    const normalCore = new THREE.Quaternion();
    const step = new THREE.Quaternion();
    const offset = new THREE.Vector3();
    const activeAxis = new THREE.Vector3();
    let phaseMiddle = 0;
    let phaseOuter = 0;
    let phaseCore = 0;
    let expansion = 0;
    renderer.setAnimationLoop(() => {
      const dt = Math.min(clock.getDelta(), 0.25);
      const activity = modeRef.current;
      key.intensity = activity === 'thinking' ? 3.8 + Math.sin(clock.elapsedTime * 5) * 0.45
        : activity === 'speaking' ? 3.6 + Math.sin(clock.elapsedTime * 9) * 0.65
        : activity === 'error' ? 2.4 : 3.2;
      phaseMiddle = (phaseMiddle + dt * TAU / 6) % TAU;
      phaseOuter = (phaseOuter - dt * TAU / 8) % TAU;
      phaseCore = (phaseCore + dt * TAU / 4) % TAU;
      normalMiddle.setFromAxisAngle(SHARED_AXIS, phaseMiddle);
      normalOuter.setFromAxisAngle(SHARED_AXIS, phaseOuter);
      normalCore.setFromAxisAngle(THREE.Object3D.DEFAULT_UP, phaseCore);
      const target = hold.current ? 1 : 0;
      expansion += (target - expansion) * (1 - Math.exp(-dt / (hold.current ? 0.65 : 1.7)));
      if (core) core.quaternion.copy(normalCore).multiply(coreBase);
      let allHome = true;
      for (const satellite of satellites) {
        const normal = satellite.tier === 'middle' ? normalMiddle : normalOuter;
        if (!independent) {
          satellite.orbit.copy(normal);
        } else {
          const regularSpeed = satellite.tier === 'middle' ? TAU / 6 : -TAU / 8;
          activeAxis.copy(SHARED_AXIS).lerp(satellite.axis, expansion).normalize();
          step.setFromAxisAngle(activeAxis, (regularSpeed + (satellite.speed - regularSpeed) * expansion) * dt);
          satellite.orbit.premultiply(step);
          if (!hold.current) satellite.orbit.slerp(normal, 1 - Math.exp(-dt * 2.2 * (1 - expansion)));
        }
        if (satellite.orbit.angleTo(normal) >= 0.03) allHome = false;
        offset.copy(satellite.basePosition).sub(CENTER).applyQuaternion(satellite.orbit);
        satellite.mesh.position.copy(CENTER).addScaledVector(offset, 1 + expansion * 0.25);
        satellite.mesh.position.y += expansion * (satellite.tier === 'outer' ? 0.06 : 0.04);
        satellite.mesh.quaternion.copy(satellite.orbit).multiply(satellite.baseRotation);
      }
      if (!hold.current && expansion < 0.03 && allHome && independent) {
        independent = false;
        setStatus('常规循环：中层与外层反向旋转。按住核心可再次激活。');
      }
      renderer.render(scene, camera);
    });

    return () => {
      disposed = true;
      hold.current = false;
      renderer.setAnimationLoop(null);
      observer.disconnect();
      renderer.domElement.removeEventListener('pointerdown', onPointerDown);
      renderer.domElement.removeEventListener('pointerup', onPointerUp);
      renderer.domElement.removeEventListener('pointercancel', onPointerUp);
      renderer.domElement.removeEventListener('lostpointercapture', onPointerUp);
      window.removeEventListener('pointerup', onPointerUp);
      host.removeEventListener('keydown', onKeyDown);
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, []);

  return <div className="core-viewer"><div className={`core-canvas is-${mode}`} ref={mount} role="button" tabIndex={0} aria-label="点击核心开始或结束语音；按住核心激活装甲动画" /><p role="status">{status}</p></div>;
}
