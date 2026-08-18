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
import { Line2 } from 'three/examples/jsm/lines/Line2.js';
import { LineGeometry } from 'three/examples/jsm/lines/LineGeometry.js';
import { LineMaterial } from 'three/examples/jsm/lines/LineMaterial.js';
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
  private manualPreviewArrow: THREE.ArrowHelper | null = null;
  private sideActionArrows: THREE.ArrowHelper[] = [];
  private partingLines: Line2[] = [];
  private faceBoundaryLines: THREE.LineSegments | null = null;
  private faceBoundariesEnabled = false;
  private readonly raycaster = new THREE.Raycaster();

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
    // F12 §8: LineMaterial (fat lines) resolves its screen-space width from
    // this uniform -- must be kept in sync with the actual render target
    // size or the parting-line curve silently reverts to hairline-thin.
    for (const line of this.partingLines) {
      (line.material as LineMaterial).resolution.set(clientWidth, clientHeight);
    }
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

    // F10 §2: a new mesh invalidates any previously-built boundary geometry
    // (different vertex/index buffers) -- rebuild it for the new part if the
    // overlay is currently on, exactly like overlayColors above.
    this.rebuildFaceBoundaries();
  }

  /**
   * F10 §2: "Show Face Boundaries" -- an optional, purely visual overlay
   * distinct from analysis overlays (draft/undercut/core-cavity coloring):
   * it never touches `overlayColors`, never changes what's analyzed, and
   * never creates a second viewer. Draws the REAL topological face
   * boundaries (edges where two triangles carry different `face_id`s, or a
   * mesh boundary edge used by only one triangle) computed directly from
   * the already-loaded `AdaptedMesh` -- not every triangulation edge, which
   * would just show the mesh's internal tessellation, not the CAD topology.
   */
  setShowFaceBoundaries(show: boolean): void {
    this.faceBoundariesEnabled = show;
    this.rebuildFaceBoundaries();
  }

  private rebuildFaceBoundaries(): void {
    if (this.faceBoundaryLines) {
      this.scene.remove(this.faceBoundaryLines);
      this.faceBoundaryLines.geometry.dispose();
      (this.faceBoundaryLines.material as THREE.Material).dispose();
      this.faceBoundaryLines = null;
    }
    if (!this.faceBoundariesEnabled || !this.currentMesh) return;

    const { positions, indices, faceIds } = this.currentMesh;
    const triangleCount = indices.length / 3;
    // F12: fixed -- STEP faces are triangulated INDEPENDENTLY by OCC and
    // then concatenated into one buffer (backend/geometry/visualize_raw.py),
    // so two adjacent faces' triangulations do NOT share vertex INDICES at
    // their common edge even though the positions geometrically coincide --
    // matching by (faceIdA, faceIdB) pairs on a shared vertex index (the
    // previous approach) therefore never found a boundary at all. The
    // correct, index-scheme-independent definition: within ONE face_id's
    // own triangle set, an edge used by exactly one triangle is that face's
    // own outer boundary (its triangulation is a manifold 2-D mesh of a
    // single bounded surface); an edge used by two triangles of the SAME
    // face_id is internal tessellation. This needs no cross-face matching
    // at all, so it is correct regardless of how neighboring faces' meshes
    // are indexed.
    const edgeCountWithinFace = new Map<string, number>();
    const edgeVertexPair = new Map<string, [number, number]>();
    for (let t = 0; t < triangleCount; t++) {
      const faceId = faceIds[t] ?? -1;
      const a = indices[t * 3];
      const b = indices[t * 3 + 1];
      const c = indices[t * 3 + 2];
      const edges: [number, number][] = [
        [a, b],
        [b, c],
        [c, a],
      ];
      for (const [v0, v1] of edges) {
        const [lo, hi] = v0 < v1 ? [v0, v1] : [v1, v0];
        const key = `${faceId}_${lo}_${hi}`;
        edgeCountWithinFace.set(key, (edgeCountWithinFace.get(key) ?? 0) + 1);
        if (!edgeVertexPair.has(key)) edgeVertexPair.set(key, [lo, hi]);
      }
    }

    const boundaryPositions: number[] = [];
    for (const [key, count] of edgeCountWithinFace) {
      if (count === 1) {
        const [v0, v1] = edgeVertexPair.get(key)!;
        boundaryPositions.push(
          positions[v0 * 3], positions[v0 * 3 + 1], positions[v0 * 3 + 2],
          positions[v1 * 3], positions[v1 * 3 + 1], positions[v1 * 3 + 2],
        );
      }
    }
    if (boundaryPositions.length === 0) return;

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(boundaryPositions), 3));
    // F12 §9: bright, high-contrast, visible over shaded overlay colors in
    // either theme -- the previous near-black line was legible only against
    // light default-grey faces, not saturated overlay colors.
    const material = new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.9 });
    this.faceBoundaryLines = new THREE.LineSegments(geometry, material);
    this.faceBoundaryLines.renderOrder = 5;
    this.scene.add(this.faceBoundaryLines);
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
   * F13 §8: geometric centroid of a face group's own displayed triangles --
   * the placement point for a side-action movement arrow. Plain mean of
   * every matching triangle's vertices (not area-weighted); good enough for
   * "put the arrow near this group," which is all an arrow origin needs to
   * be. Returns `null` if none of `faceIds` appear in the loaded mesh.
   */
  getFaceCentroid(faceIds: number[]): Vec3 | null {
    if (!this.currentMesh) return null;
    const { positions, indices, faceIds: meshFaceIds } = this.currentMesh;
    const wanted = new Set(faceIds);
    const sum = new THREE.Vector3();
    let matched = 0;
    const triangleCount = indices.length / 3;
    for (let t = 0; t < triangleCount; t++) {
      if (!wanted.has(meshFaceIds[t] ?? -1)) continue;
      for (const idx of [indices[t * 3], indices[t * 3 + 1], indices[t * 3 + 2]]) {
        sum.add(new THREE.Vector3(positions[idx * 3], positions[idx * 3 + 1], positions[idx * 3 + 2]));
        matched += 1;
      }
    }
    if (matched === 0) return null;
    sum.divideScalar(matched);
    return [sum.x, sum.y, sum.z];
  }

  /**
   * F13 §8: one arrow per delegated side-action group, each drawn from the
   * REAL backend-validated `movement_direction` (D-044's
   * `DelegatedSecondaryAction`) at that group's own face centroid -- never
   * fabricated when the backend hasn't supplied a valid (non-zero) vector
   * for a group, which this simply skips rather than substituting a guess.
   * `null` clears every arrow (tool switch away from a side-action view).
   */
  setSideActionArrows(groups: { faceIds: number[]; direction: Vec3 }[] | null, length = 40): void {
    for (const arrow of this.sideActionArrows) {
      this.scene.remove(arrow);
      arrow.dispose();
    }
    this.sideActionArrows = [];
    if (!groups) return;
    const color = 0xc86edb; // --vis-side-action
    for (const group of groups) {
      const dir = new THREE.Vector3(...group.direction);
      if (dir.lengthSq() < 1e-12) continue; // no valid backend vector for this group -- skip, never invent
      dir.normalize();
      const origin = this.getFaceCentroid(group.faceIds);
      if (!origin) continue;
      const arrow = new THREE.ArrowHelper(dir, new THREE.Vector3(...origin), length, color, length * 0.3, length * 0.18);
      this.sideActionArrows.push(arrow);
      this.scene.add(arrow);
    }
  }

  /**
   * F12 §6/§11: real click-to-inspect face picking -- replaces the F1
   * placeholder that always selected face 0 regardless of where the user
   * clicked. Pure CPU-side geometry raycasting (three.js's `Raycaster`
   * against the already-loaded mesh), independent of whether a WebGL
   * context exists, so it works the same way `getFaceNormal` above already
   * does. `ndcX`/`ndcY` are normalized device coordinates (-1..1) computed
   * by the caller from the click position relative to the canvas -- this
   * method holds no DOM/event knowledge of its own. Returns `null` for a
   * click that doesn't hit the mesh (e.g. empty space) -- the caller should
   * leave the current selection untouched in that case, not clear it or
   * substitute an arbitrary face.
   */
  pickFaceId(ndcX: number, ndcY: number): number | null {
    if (!this.meshObject || !this.currentMesh) return null;
    this.raycaster.setFromCamera(new THREE.Vector2(ndcX, ndcY), this.camera);
    const hits = this.raycaster.intersectObject(this.meshObject, false);
    const hit = hits[0];
    if (!hit || hit.faceIndex === undefined || hit.faceIndex === null) return null;
    return this.currentMesh.faceIds[hit.faceIndex] ?? null;
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

  /**
   * F7: the "manual draft" preview arrow -- a second, visually distinct
   * indicator shown ONLY while the engineer is actively editing the Manual
   * Pull Direction vector (`PullDirectionPanel`), alongside (not instead of)
   * `setDirectionArrow`'s already-resolved direction. Steel-blue rather than
   * the accent copper, so "what the analysis actually used" and "what I'm
   * about to try" never look like the same thing.
   */
  setManualDirectionPreview(direction: Vec3 | null, origin: Vec3 = [0, 0, 0], length = 60): void {
    if (this.manualPreviewArrow) {
      this.scene.remove(this.manualPreviewArrow);
      this.manualPreviewArrow.dispose();
      this.manualPreviewArrow = null;
    }
    if (!direction) return;
    const dir = new THREE.Vector3(...direction);
    if (dir.lengthSq() < 1e-12) return;
    dir.normalize();
    this.manualPreviewArrow = new THREE.ArrowHelper(
      dir,
      new THREE.Vector3(...origin),
      length,
      0x5fb8e0,
      length * 0.25,
      length * 0.15,
    );
    this.scene.add(this.manualPreviewArrow);
  }

  /** F7: theme-driven viewport ground -- see `theme/useTheme.ts`. Accepts any CSS color string three.js can parse (hex, rgb()). */
  setBackgroundColor(cssColor: string): void {
    this.scene.background = new THREE.Color(cssColor);
  }

  /**
   * F7/F12 §8: the parting-line curve overlay -- `parting_line_path` from
   * `GET /parts/{filename}/parting-line-v2` (the authoritative v2 engine's
   * selected candidate), drawn directly from the backend's own point list,
   * never a client-side approximation. `null`/empty clears every currently
   * drawn line. Uses `Line2`/`LineMaterial` (three.js's "fat lines" example
   * module) instead of plain `THREE.Line` -- WebGL1's native line width is
   * effectively fixed at 1px on most platforms regardless of `linewidth`,
   * which made the curve nearly invisible against a shaded, overlay-colored
   * mesh; `LineMaterial.linewidth` is real screen-space pixels, kept in
   * sync with the render target size in `resize()`.
   */
  setPartingLines(paths: { points: Vec3[]; colorHex: string; opacity?: number }[] | null): void {
    for (const line of this.partingLines) {
      this.scene.remove(line);
      line.geometry.dispose();
      (line.material as LineMaterial).dispose();
    }
    this.partingLines = [];
    if (!paths) return;
    const width = this.container?.clientWidth || 1;
    const height = this.container?.clientHeight || 1;
    for (const path of paths) {
      if (path.points.length < 2) continue;
      const flatPositions: number[] = [];
      for (const [x, y, z] of path.points) flatPositions.push(x, y, z);
      const geometry = new LineGeometry();
      geometry.setPositions(flatPositions);
      const material = new LineMaterial({
        color: new THREE.Color(path.colorHex).getHex(),
        linewidth: 5, // screen-space pixels, not world units
        transparent: path.opacity !== undefined && path.opacity < 1,
        opacity: path.opacity ?? 1,
        depthTest: false, // never hidden behind the shaded mesh surface
        worldUnits: false,
      });
      material.resolution.set(width, height);
      const line = new Line2(geometry, material);
      line.computeLineDistances();
      line.renderOrder = 10;
      this.partingLines.push(line);
      this.scene.add(line);
    }
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
    this.manualPreviewArrow?.dispose();
    this.manualPreviewArrow = null;
    this.setPartingLines(null);
    if (this.faceBoundaryLines) {
      this.faceBoundaryLines.geometry.dispose();
      (this.faceBoundaryLines.material as THREE.Material).dispose();
      this.faceBoundaryLines = null;
    }
    this.renderer?.dispose();
    this.renderer = null;
  }
}

const DEFAULT_CAMERA: CameraState = {
  position: [120, 90, 120],
  target: [0, 0, 0],
  zoom: 1,
};
