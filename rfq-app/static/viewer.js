/* RFQ 3D file viewer.
 * Uploads the selected CAD file to /rfq/upload (STEP is tessellated server-side),
 * then renders the returned STL mesh with three.js (vendored, r128). Also drives
 * the tight-tolerance UI (show/hide + blueprint-required) and the material hint.
 */
(function () {
  "use strict";

  var container = document.getElementById("viewer");
  var placeholder = document.getElementById("viewer-placeholder");
  var dimsEl = document.getElementById("viewer-dims");
  var statusEl = document.getElementById("upload-status");
  var fileInput = document.getElementById("cad_file");
  var draftInput = document.getElementById("draft_id");

  var scene, camera, renderer, controls, mesh, animating = false;

  function initThree() {
    if (renderer) return;
    var width = container.clientWidth || 480;
    var height = container.clientHeight || 380;

    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x11161c);

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
    var key = new THREE.DirectionalLight(0xffffff, 0.85);
    key.position.set(1, 1.3, 1);
    scene.add(key);
    var fill = new THREE.DirectionalLight(0xffa259, 0.35);
    fill.position.set(-1, -0.5, -0.8);
    scene.add(fill);

    var grid = new THREE.GridHelper(400, 20, 0x2a333d, 0x1e252d);
    grid.name = "grid";
    scene.add(grid);

    window.addEventListener("resize", onResize);
    if (!animating) {
      animating = true;
      animate();
    }
  }

  function onResize() {
    if (!renderer) return;
    var width = container.clientWidth || 480;
    var height = container.clientHeight || 380;
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
    if (mesh) {
      scene.remove(mesh);
      if (mesh.geometry) mesh.geometry.dispose();
      if (mesh.material) mesh.material.dispose();
      mesh = null;
    }
  }

  function frameObject(geometry) {
    geometry.computeBoundingBox();
    var box = geometry.boundingBox;
    var size = new THREE.Vector3();
    var center = new THREE.Vector3();
    box.getSize(size);
    box.getCenter(center);

    geometry.translate(-center.x, -center.y, -center.z);

    var maxDim = Math.max(size.x, size.y, size.z) || 1;
    var grid = scene.getObjectByName("grid");
    if (grid) {
      grid.scale.setScalar(maxDim / 20);
      grid.position.y = -size.y / 2;
    }

    var dist = maxDim * 2.2;
    camera.near = maxDim / 100;
    camera.far = maxDim * 100;
    camera.updateProjectionMatrix();
    camera.position.set(dist, dist * 0.8, dist);
    controls.target.set(0, 0, 0);
    controls.update();
    return size;
  }

  function loadMesh(url) {
    initThree();
    var loader = new THREE.STLLoader();
    loader.load(
      url,
      function (geometry) {
        clearMesh();
        var material = new THREE.MeshPhongMaterial({
          color: 0xff7a1a,
          specular: 0x222222,
          shininess: 40,
          flatShading: false,
        });
        mesh = new THREE.Mesh(geometry, material);
        frameObject(geometry);
        scene.add(mesh);
        if (placeholder) placeholder.style.display = "none";
      },
      undefined,
      function () {
        setStatus("Could not render the mesh in the viewer.", true);
      }
    );
  }

  function setStatus(msg, isError) {
    if (!statusEl) return;
    statusEl.textContent = msg || "";
    statusEl.classList.toggle("status-error", !!isError);
  }

  function showDims(bbox, fmt) {
    if (!dimsEl) return;
    if (!bbox) {
      dimsEl.textContent = fmt === "step"
        ? "STEP loaded (measured in mm)."
        : "";
      return;
    }
    var f = function (n) { return (Math.round(n * 1000) / 1000).toFixed(3); };
    dimsEl.textContent =
      "Bounding box: " + f(bbox.x) + " × " + f(bbox.y) + " × " + f(bbox.z) + " in";
  }

  function uploadFile(file) {
    setStatus("Uploading and preparing " + file.name + "…", false);
    var data = new FormData();
    data.append("cad_file", file);
    fetch("/rfq/upload", { method: "POST", body: data })
      .then(function (resp) {
        return resp.json().then(function (json) {
          return { ok: resp.ok, json: json };
        });
      })
      .then(function (res) {
        if (!res.ok) {
          setStatus(res.json.error || "Upload failed.", true);
          return;
        }
        draftInput.value = res.json.draft_id;
        setStatus("Loaded " + res.json.original_name + ".", false);
        showDims(res.json.bbox_in, res.json.format);
        loadMesh(res.json.mesh_url);
      })
      .catch(function () {
        setStatus("Upload failed — check your connection and try again.", true);
      });
  }

  if (fileInput) {
    fileInput.addEventListener("change", function () {
      if (fileInput.files && fileInput.files.length) {
        // A new file invalidates any prior draft; server re-tessellates.
        draftInput.value = "";
        uploadFile(fileInput.files[0]);
      }
    });
  }

  /* Tight-tolerance UI ---------------------------------------------------- */
  var tolStandard = document.getElementById("tol-standard");
  var tolTight = document.getElementById("tol-tight");
  var tightOptions = document.getElementById("tight-options");
  var blueprintInput = document.getElementById("blueprint_file");

  function syncTolerance() {
    var tight = tolTight && tolTight.checked;
    if (tightOptions) tightOptions.hidden = !tight;
    if (blueprintInput) blueprintInput.required = !!tight;
  }
  if (tolStandard) tolStandard.addEventListener("change", syncTolerance);
  if (tolTight) tolTight.addEventListener("change", syncTolerance);
  syncTolerance();

  /* Standard-tolerance hint for the selected material --------------------- */
  var materialSelect = document.getElementById("material");
  var tolHint = document.getElementById("standard-tol-hint");
  function syncMaterialHint() {
    if (!materialSelect || !tolHint) return;
    var opt = materialSelect.options[materialSelect.selectedIndex];
    if (!opt) return;
    var cls = opt.getAttribute("data-class") || "metal";
    var std = opt.getAttribute("data-standard");
    tolHint.textContent = "Standard quality for " + cls + ": ±" + std + '" — tighter than this is "tight".';
  }
  if (materialSelect) materialSelect.addEventListener("change", syncMaterialHint);
  syncMaterialHint();
})();
