/**
 * Vanilla three.js engine -- deliberately NOT a React component and
 * deliberately created exactly once per `<Viewport />` mount.
 *
 * This is the mechanism the persistence requirement (F1 spec, "PERSISTENT
 * VIEWPORT REQUIREMENT") rests on: because `Viewport.tsx` is mounted once
 * at `WorkstationShell` level and never conditionally rendered per tool
 * (see WorkstationShell.tsx), this engine's `scene`/`camera`/`renderer`
 * instances live for the lifetime of the whole session. Switching the
 * active tool re-renders `ContextInspector` only -- nothing here is
 * touched, so camera position, loaded geometry, and selection highlighting
 * survive automatically, by construction, not by special-casing.
 *
 * WebGL is optional at construction time (not available under jsdom, and
 * not guaranteed on every CI runner) -- `renderer` is `null` and every
 * method becomes a no-op rather than throwing, so this engine (and the
 * component wrapping it) is exercised the same way in tests as in a real
 * browser.
 */

import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import type { AdaptedMesh } from '../geometry/meshAdapter';
import type { CameraState } from '../store/analysisStore';
import type { Vec3 } from '../domain/types';

const SELECTED_COLOR = new THREE.Color('#d97b3f'); // --accent
const DEFAULT_COLOR = new THREE.Color('#7c8794');

export class ViewportEngine {
  readonly scene: THREE.Scene;
  readonly camera: THREE.PerspectiveCamera;
  private renderer: THREE.WebGLRenderer | null = null;
  private controls: OrbitControls | null = null;
  private container: HTMLElement | null = null;
  private meshObject: THREE.Mesh | null = null;
  private currentMesh: AdaptedMesh | null = null;
  private selectedFaceIds: Set<number> = new Set();
  private overlayColors: Map<number, THREE.Color> | null = null;
  private frameHandle: number | null = null;
  private resizeObserver: ResizeObserver | null = null;
  private directionArrow: THREE.ArrowHelper | null = null;

  constructor() {
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color('#101317'); // --viewport-bg

    this.camera = new THREE.PerspectiveCamera(45, 1, 0.1, 10000);
    this.camera.position.set(...DEFAULT_CAMERA.position);
    this.camera.lookAt(...DEFAULT_CAMERA.target);

    const key = new THREE.DirectionalLight(0xffffff, 1.1);
    key.position.set(120, 160, 100);
    const fill = new THREE.AmbientLight(0xffffff, 0.45);
    this.scene.add(key, fill);

    const grid = new THREE.GridHelper(240, 24, 0x2c323b, 0x1e2229);
    this.scene.add(grid);
  }

  /** True once a real WebGL context was successfully created. */
  get hasRenderer(): boolean {
    return this.renderer !== null;
  }

  mount(container: HTMLElement): void {
    // Idempotent: React 18/19 StrictMode double-invokes mount-effects in
    // development. If already mounted into this exact container (or the
    // renderer already exists from a prior mount into the same node),
    // re-mounting must not create a second renderer/observer/render loop.
    if (this.container === container && this.renderer) {
      return;
    }
    this.container = container;
    if (!this.renderer) {
      try {
        this.renderer = new THREE.WebGLRenderer({ antialias: true });
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      } catch {
        // No WebGL available (jsdom, some CI runners, exotic GPU drivers).
        // The engine keeps running headless: scene/camera/selection state
        // all still work, only pixels are skipped.
        this.renderer = null;
      }
    }
    if (this.renderer) {
      if (this.renderer.domElement.parentElement !== container) {
        container.appendChild(this.renderer.domElement);
      }
      this.resize();
      if (!this.resizeObserver) {
        this.resizeObserver = new ResizeObserver(() => this.resize());
        this.resizeObserver.observe(container);
      }
      if (!this.controls) {
        this.controls = new OrbitControls(this.camera, this.renderer.domElement);
        this.controls.target.set(...DEFAULT_CAMERA.target);
        this.controls.enableDamping = true;
        this.controls.dampingFactor = 0.08;
        this.controls.update();
      }
      if (this.frameHandle === null) {
        this.startRenderLoop();
      }
    }
  }

  unmountFromDom(): void {
    // Detach from the DOM/observe cycle without destroying scene state --
    // used only if a caller needs to briefly move the canvas. Not used by
    // Viewport.tsx today (the container never disappears), kept minimal and
    // explicit rather than folded into dispose().
    if (this.resizeObserver) {
      this.resizeObserver.disconnect();
      this.resizeObserver = null;
    }
    if (this.frameHandle !== null) {
      cancelAnimationFrame(this.frameHandle);
      this.frameHandle = null;
    }
    if (this.renderer && this.renderer.domElement.parentElement) {
      this.renderer.domElement.parentElement.removeChild(this.renderer.domElement);
    }
  }

  private resize(): void {
    if (!this.renderer || !this.container) return;
    const { clientWidth, clientHeight } = this.container;
    if (clientWidth === 0 || clientHeight === 0) return;
    this.camera.aspect = clientWidth / clientHeight;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(clientWidth, clientHeight);
  }

  private startRenderLoop(): void {
    const tick = () => {
      this.frameHandle = requestAnimationFrame(tick);
      this.controls?.update();
      if (this.renderer) {
        this.renderer.render(this.scene, this.camera);
      }
    };
    tick();
  }

  setMesh(mesh: AdaptedMesh): void {
    this.currentMesh = mesh;
    // A new mesh means a new (or newly re-loaded) part -- any overlay
    // colored for the PREVIOUS part's face_ids must not silently carry over
    // and coincidentally mis-color the new part's faces. Analysis overlays
    // are re-applied deliberately, per result, never assumed to survive a
    // geometry swap.
    this.overlayColors = null;
    if (this.meshObject) {
      this.scene.remove(this.meshObject);
      this.meshObject.geometry.dispose();
      (this.meshObject.material as THREE.Material).dispose();
      this.meshObject = null;
    }

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(mesh.positions, 3));
    geometry.setIndex(new THREE.BufferAttribute(mesh.indices, 1));
    geometry.computeVertexNormals();

    const colors = new Float32Array(mesh.positions.length);
    this.paintFaceColors(geometry, mesh, colors);

    const material = new THREE.MeshStandardMaterial({
      vertexColors: true,
      metalness: 0.15,
      roughness: 0.65,
      side: THREE.DoubleSide,
    });
    this.meshObject = new THREE.Mesh(geometry, material);
    this.scene.add(this.meshObject);
  }

  private paintFaceColors(geometry: THREE.BufferGeometry, mesh: AdaptedMesh, colors: Float32Array): void {
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    const colorAttr = geometry.getAttribute('color') as THREE.BufferAttribute;
    const triangleCount = mesh.indices.length / 3;
    for (let t = 0; t < triangleCount; t++) {
      const faceId = mesh.faceIds[t] ?? -1;
      const color = this.selectedFaceIds.has(faceId)
        ? SELECTED_COLOR
        : (this.overlayColors?.get(faceId) ?? DEFAULT_COLOR);
      for (let corner = 0; corner < 3; corner++) {
        const vertexIndex = mesh.indices[t * 3 + corner];
        colorAttr.setXYZ(vertexIndex, color.r, color.g, color.b);
      }
    }
    colorAttr.needsUpdate = true;
  }

  setSelection(faceIds: number[]): void {
    this.selectedFaceIds = new Set(faceIds);
    this.repaint();
  }

  /**
   * F3: per-face overlay coloring (e.g. core/cavity/parting classification
   * from `/core-cavity`'s `display_mesh.core_cavity_rgb`, parallel to
   * `mesh.face_ids`). `null` clears back to `DEFAULT_COLOR`. Selection
   * highlighting still wins over an overlay color for a selected face --
   * matches F1's existing selection-first precedence, unchanged.
   */
  setOverlayColors(colors: Map<number, THREE.Color> | null): void {
    this.overlayColors = colors;
    this.repaint();
  }

  private repaint(): void {
    if (this.meshObject && this.currentMesh) {
      const colors = (this.meshObject.geometry.getAttribute('color') as THREE.BufferAttribute).array as Float32Array;
      this.paintFaceColors(this.meshObject.geometry, this.currentMesh, colors);
    }
  }

  /**
   * F4: a convenience starting point for the Manual Pull Direction editor
   * ("face selection from the viewport" -- F4 spec) -- the geometric normal
   * of the picked face's own displayed triangles (averaged if it has more
   * than one), computed directly from the already-loaded mesh positions,
   * never a second backend call. This is NOT the authoritative B-Rep normal
   * `backend/models/geometry_models.py`'s `FaceData.normal` carries (that
   * would need `/summary?include_faces=true`, a materially larger payload
   * F2 deliberately never requests) -- it only pre-fills the X/Y/Z fields;
   * the engineer can review/edit the numbers before running, and the
   * backend's own `resolve_manual_direction_mold` normalizes/validates
   * whatever is actually submitted regardless. Returns `null` if no
   * triangle carries this `faceId` or no mesh is loaded.
   */
  getFaceNormal(faceId: number): Vec3 | null {
    if (!this.currentMesh) return null;
    const { positions, indices, faceIds } = this.currentMesh;
    const accumulated = new THREE.Vector3();
    let matched = 0;
    const triangleCount = indices.length / 3;
    const a = new THREE.Vector3();
    const b = new THREE.Vector3();
    const c = new THREE.Vector3();
    for (let t = 0; t < triangleCount; t++) {
      if (faceIds[t] !== faceId) continue;
      const ia = indices[t * 3];
      const ib = indices[t * 3 + 1];
      const ic = indices[t * 3 + 2];
      a.set(positions[ia * 3], positions[ia * 3 + 1], positions[ia * 3 + 2]);
      b.set(positions[ib * 3], positions[ib * 3 + 1], positions[ib * 3 + 2]);
      c.set(positions[ic * 3], positions[ic * 3 + 1], positions[ic * 3 + 2]);
      const normal = new THREE.Vector3().subVectors(b, a).cross(new THREE.Vector3().subVectors(c, a));
      if (normal.lengthSq() > 1e-12) {
        accumulated.add(normal.normalize());
        matched += 1;
      }
    }
    if (matched === 0) return null;
    accumulated.normalize();
    return [accumulated.x, accumulated.y, accumulated.z];
  }

  /**
   * F4: a live, non-interactive direction indicator for the Manual Pull
   * Direction editor -- updates as the engineer edits the vector, so the
   * direction is visible in context against the part before running
   * anything. Deliberately NOT a draggable gizmo: a drag-to-set control
   * would need its own pointer-event/raycast handling layered over
   * `OrbitControls`' existing camera-drag handling on the same canvas, a
   * real risk to the persistent viewport's stability that F4's spec
   * explicitly permits skipping ("if it can be implemented cleanly without
   * destabilizing..."). An `ArrowHelper` is a plain scene object -- adding,
   * moving, or removing it never touches controls, listeners, or the
   * render loop. `null` removes it.
   */
  setDirectionArrow(direction: Vec3 | null, origin: Vec3 = [0, 0, 0], length = 60): void {
    if (this.directionArrow) {
      this.scene.remove(this.directionArrow);
      this.directionArrow.dispose();
      this.directionArrow = null;
    }
    if (!direction) return;
    const dir = new THREE.Vector3(...direction);
    if (dir.lengthSq() < 1e-12) return; // never normalized for display of a literal zero vector
    dir.normalize();
    this.directionArrow = new THREE.ArrowHelper(dir, new THREE.Vector3(...origin), length, 0xd97b3f, length * 0.25, length * 0.15);
    this.scene.add(this.directionArrow);
  }

  applyCameraState(state: CameraState): void {
    this.camera.position.set(...state.position);
    this.camera.zoom = state.zoom;
    this.camera.updateProjectionMatrix();
    this.controls?.target.set(...state.target);
    this.camera.lookAt(...state.target);
    this.controls?.update();
  }

  readCameraState(): CameraState {
    const target = this.controls
      ? ([this.controls.target.x, this.controls.target.y, this.controls.target.z] as const)
      : DEFAULT_CAMERA.target;
    return {
      position: [this.camera.position.x, this.camera.position.y, this.camera.position.z],
      target,
      zoom: this.camera.zoom,
    };
  }

  /**
   * F2: re-frame the camera around a newly-loaded part's real bounding box
   * (from `PartSummaryResponse.bounding_box`) -- the previous camera state
   * was framed for whatever part (or the F1 sample solid) was loaded
   * before, and keeping it would likely point at empty space or clip
   * through geometry of a very different size. This is a geometry-load
   * concern, not "analysis state" -- it runs whenever a NEW mesh is set,
   * never on a tool switch.
   */
  frameToBoundingBox(center: Vec3, diagonalMm: number): void {
    const radius = Math.max(diagonalMm / 2, 1);
    const direction = new THREE.Vector3(1, 0.75, 1).normalize();
    const distance = radius / Math.sin((this.camera.fov * Math.PI) / 360) || radius * 2.2;
    const eye = direction.multiplyScalar(distance * 1.15).add(new THREE.Vector3(...center));

    this.camera.position.copy(eye);
    this.camera.near = Math.max(distance / 100, 0.01);
    this.camera.far = distance * 100;
    this.camera.updateProjectionMatrix();
    this.controls?.target.set(...center);
    this.camera.lookAt(...center);
    this.controls?.update();
  }

  dispose(): void {
    this.unmountFromDom();
    this.controls?.dispose();
    this.controls = null;
    if (this.meshObject) {
      this.meshObject.geometry.dispose();
      (this.meshObject.material as THREE.Material).dispose();
    }
    this.directionArrow?.dispose();
    this.directionArrow = null;
    this.renderer?.dispose();
    this.renderer = null;
  }
}

const DEFAULT_CAMERA: CameraState = {
  position: [120, 90, 120],
  target: [0, 0, 0],
  zoom: 1,
};
