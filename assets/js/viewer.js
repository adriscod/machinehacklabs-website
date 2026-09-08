/**
 * /quote/ 3D preview. Vendored three.js r128 + STLLoader + OrbitControls.
 *
 * STL loads in the browser. STEP is tessellated by the local 8765 server
 * (POST /__local_tessellate). If that endpoint is missing, the viewer shows
 * an AABB from CARTESIAN_POINT data so the estimate path still has a preview.
 */
/* global THREE */

import { detectFormat, measureCadFile } from "./estimator.js";

const TESSELLATE_PATH = "/__local_tessellate";
const MESH_COLOR = 0xd4782c;
const SCENE_BG = 0x100e0a;

const container = document.getElementById("part-viewer");
const placeholder = document.getElementById("viewer-placeholder");
const statusEl =
  document.getElementById("upload-status") || document.getElementById("viewer-status");
const dimsEl = document.getElementById("viewer-dims");

let scene;
let camera;
let renderer;
let controls;
let mesh;
let animating = false;
let previewGen = 0;

function hasThree() {
  return typeof THREE !== "undefined" && THREE.WebGLRenderer && THREE.STLLoader;
}

function setStatus(msg, isError) {
  if (!statusEl) return;
  statusEl.textContent = msg || "";
  statusEl.classList.toggle("status-error", Boolean(isError));
}

export function setViewerDims(bboxIn, format) {
  if (!dimsEl) return;
  if (!bboxIn) {
    dimsEl.textContent = format === "step" ? "STEP loaded (measured in mm)." : "";
    return;
  }
  const f = (n) => (Math.round(Number(n) * 1000) / 1000).toFixed(3);
  dimsEl.textContent = `Bounding box: ${f(bboxIn.x)} × ${f(bboxIn.y)} × ${f(bboxIn.z)} in`;
}

function initThree() {
  if (!container || renderer) return Boolean(renderer);
  if (!hasThree()) {
    setStatus("3D preview is unavailable in this browser.", true);
    return false;
  }

  const width = container.clientWidth || 320;
  const height = container.clientHeight || 280;

  scene = new THREE.Scene();
  scene.background = new THREE.Color(SCENE_BG);

  camera = new THREE.PerspectiveCamera(45, width / height, 0.01, 100000);
  camera.position.set(120, 90, 120);

  renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio || 1);
  renderer.setSize(width, height);
  container.appendChild(renderer.domElement);

  controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;

  scene.add(new THREE.AmbientLight(0xffffff, 0.55));
  const key = new THREE.DirectionalLight(0xffffff, 0.85);
  key.position.set(1, 1.3, 1);
  scene.add(key);
  const fill = new THREE.DirectionalLight(0xd4782c, 0.35);
  fill.position.set(-1, -0.5, -0.8);
  scene.add(fill);

  const grid = new THREE.GridHelper(400, 20, 0x3b3628, 0x211e16);
  grid.name = "grid";
  scene.add(grid);

  window.addEventListener("resize", onResize);
  if (!animating) {
    animating = true;
    animate();
  }
  return true;
}

function onResize() {
  if (!renderer || !container) return;
  const width = container.clientWidth || 320;
  const height = container.clientHeight || 280;
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
  renderer.setSize(width, height);
}

function animate() {
  requestAnimationFrame(animate);
  if (controls) controls.update();
  if (renderer) renderer.render(scene, camera);
}

function clearMesh() {
  if (!scene || !mesh) return;
  scene.remove(mesh);
  mesh.traverse((child) => {
    if (child.geometry) child.geometry.dispose();
    if (child.material) {
      if (Array.isArray(child.material)) {
        child.material.forEach((mat) => mat.dispose());
      } else {
        child.material.dispose();
      }
    }
  });
  mesh = null;
}

function frameObject(geometry) {
  geometry.computeBoundingBox();
  const box = geometry.boundingBox;
  const size = new THREE.Vector3();
  const center = new THREE.Vector3();
  box.getSize(size);
  box.getCenter(center);
  geometry.translate(-center.x, -center.y, -center.z);

  const maxDim = Math.max(size.x, size.y, size.z) || 1;
  const grid = scene.getObjectByName("grid");
  if (grid) {
    grid.scale.setScalar(maxDim / 20);
    grid.position.y = -size.y / 2;
  }

  const dist = maxDim * 2.2;
  camera.near = maxDim / 100;
  camera.far = maxDim * 100;
  camera.updateProjectionMatrix();
  camera.position.set(dist, dist * 0.8, dist);
  controls.target.set(0, 0, 0);
  controls.update();
  return size;
}

function showPlaceholder(show) {
  if (!placeholder) return;
  placeholder.style.display = show ? "" : "none";
}

function addMesh(geometry, { wireframe = false } = {}) {
  if (!initThree()) return;
  clearMesh();
  const material = new THREE.MeshPhongMaterial({
    color: MESH_COLOR,
    specular: 0x222222,
    shininess: 40,
    flatShading: false,
    wireframe,
    transparent: wireframe,
    opacity: wireframe ? 0.85 : 1,
  });
  mesh = new THREE.Mesh(geometry, material);
  if (wireframe) {
    const edges = new THREE.LineSegments(
      new THREE.EdgesGeometry(geometry),
      new THREE.LineBasicMaterial({ color: 0xe8c27a })
    );
    mesh.add(edges);
  }
  frameObject(geometry);
  scene.add(mesh);
  showPlaceholder(false);
}

function loadStlUrl(url) {
  return new Promise((resolve, reject) => {
    if (!initThree()) {
      reject(new Error("3D preview is unavailable in this browser."));
      return;
    }
    const loader = new THREE.STLLoader();
    loader.load(url, resolve, undefined, () => reject(new Error("Could not render the mesh.")));
  });
}

function loadStlBuffer(buffer) {
  if (!initThree()) throw new Error("3D preview is unavailable in this browser.");
  return new THREE.STLLoader().parse(buffer);
}

async function tessellateOnServer(file) {
  const data = new FormData();
  data.append("cad_file", file);
  const resp = await fetch(TESSELLATE_PATH, { method: "POST", body: data });
  let json = {};
  try {
    json = await resp.json();
  } catch {
    json = {};
  }
  if (!resp.ok) {
    throw new Error(json.error || `Tessellation failed (${resp.status}).`);
  }
  if (!json.mesh_url) {
    throw new Error("Tessellation did not return a mesh.");
  }
  return json;
}

async function showBboxFallback(file, unit, reason) {
  const geometry = await measureCadFile(file, unit);
  const bbox = geometry.bbox_in;
  if (!bbox) throw new Error(reason || "Could not preview this file.");
  const box = new THREE.BoxGeometry(bbox.x || 0.01, bbox.y || 0.01, bbox.z || 0.01);
  addMesh(box, { wireframe: true });
  setStatus(
    reason
      ? `${reason} Showing bounding-box preview — not a solid mesh.`
      : "Bounding-box preview. The estimate still runs.",
    false
  );
}

export function resetViewer() {
  previewGen += 1;
  clearMesh();
  showPlaceholder(true);
  setStatus("", false);
  setViewerDims(null);
}

export async function previewCadFile(file, unit = "inch") {
  const gen = ++previewGen;
  if (!file) {
    resetViewer();
    return;
  }
  if (!container) return;

  setStatus(`Preparing preview of ${file.name}…`, false);
  try {
    const format = detectFormat(file.name);
    if (format === "stl") {
      const buffer = await file.arrayBuffer();
      if (gen !== previewGen) return;
      addMesh(loadStlBuffer(buffer));
      setStatus(`Loaded ${file.name}. Drag to orbit · scroll to zoom.`, false);
      return;
    }

    try {
      const draft = await tessellateOnServer(file);
      if (gen !== previewGen) return;
      const geometry = await loadStlUrl(draft.mesh_url);
      if (gen !== previewGen) return;
      addMesh(geometry);
      setStatus(`Loaded ${draft.original_name || file.name} (tessellated STEP). Drag to orbit · scroll to zoom.`, false);
    } catch (err) {
      if (gen !== previewGen) return;
      const reason = err && err.message ? String(err.message) : "STEP mesh preview is unavailable.";
      await showBboxFallback(file, unit, reason);
    }
  } catch (err) {
    if (gen !== previewGen) return;
    setStatus(err && err.message ? String(err.message) : "Could not preview this file.", true);
    showPlaceholder(true);
  }
}
