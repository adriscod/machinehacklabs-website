import {
  FEATURE_RISK_KEYS,
  SHOP_HIDDEN_FIELD_KEYS,
  buildShopPayload,
  detectFormat,
  estimateFromGeometry,
  listEnabledMaterials,
  measureCadFile,
  turnaroundTiers,
} from "./estimator.js";

const form = document.getElementById("rfq-form");
const fileInput = document.getElementById("cad_file");
const materialInput = document.getElementById("material");
const materialFilter = document.getElementById("material_filter");
const materialSourceInput = document.getElementById("material_source");
const qtyInput = document.getElementById("qty");
const setupsInput = document.getElementById("setups");
const turnaroundInput = document.getElementById("turnaround");
const dueDateInput = document.getElementById("due_date");
const toleranceInput = document.getElementById("tolerance_class");
const unitsInput = document.getElementById("units");
const stockXInput = document.getElementById("stock_x");
const stockYInput = document.getElementById("stock_y");
const stockZInput = document.getElementById("stock_z");
const estimateBox = document.getElementById("estimate-panel");
const formError = document.getElementById("form-error");
const submitBtn = document.getElementById("submit-rfq");

const FAMILY_ORDER = ["aluminum", "steel", "stainless", "plastic", "copper"];
const FAMILY_LABELS = {
  aluminum: "Aluminum",
  steel: "Steel",
  stainless: "Stainless",
  plastic: "Plastics",
  copper: "Copper alloys",
};

let quoteConfig = null;
let rfqConfig = null;
let lastEstimate = null;
let enabledMaterials = [];

function isLocalHost(hostname) {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "[::1]";
}

function moneyText(value) {
  return `$${Number(value).toFixed(2)}`;
}

function fillHidden(name, value) {
  const shop = form.querySelector(`input[type="hidden"][name="${name}"]`);
  if (shop) {
    shop.value = value == null ? "" : String(value);
    return;
  }
  const el = form.elements.namedItem(name);
  if (el && el instanceof HTMLInputElement) {
    el.value = value == null ? "" : String(value);
  }
}

function writeShopHiddens(result) {
  const payload = result ? result.shop_payload || buildShopPayload(result) : {};
  const keys = new Set([...SHOP_HIDDEN_FIELD_KEYS, ...Object.keys(payload)]);
  for (const key of keys) {
    fillHidden(key, result ? payload[key] : "");
  }
}

function familyLabel(family) {
  const key = String(family || "other").toLowerCase();
  if (FAMILY_LABELS[key]) return FAMILY_LABELS[key];
  return key ? key.charAt(0).toUpperCase() + key.slice(1) : "Other";
}

function populateMaterialSelect(filter = "") {
  const needle = filter.trim().toLowerCase();
  const prev = materialInput.value;
  const groups = new Map();
  for (const spec of enabledMaterials) {
    const hay = [spec.key, spec.label, spec.family, ...(spec.aliases || [])]
      .join(" ")
      .toLowerCase();
    if (needle && !hay.includes(needle)) continue;
    const fam = spec.family || "other";
    if (!groups.has(fam)) groups.set(fam, []);
    groups.get(fam).push(spec);
  }
  const familyKeys = [
    ...FAMILY_ORDER.filter((fam) => groups.has(fam)),
    ...[...groups.keys()].filter((fam) => !FAMILY_ORDER.includes(fam)).sort(),
  ];
  materialInput.innerHTML = "";
  for (const fam of familyKeys) {
    const og = document.createElement("optgroup");
    og.label = familyLabel(fam);
    for (const spec of groups.get(fam) || []) {
      const opt = document.createElement("option");
      opt.value = spec.key;
      opt.textContent = spec.label;
      og.appendChild(opt);
    }
    materialInput.appendChild(og);
  }
  const values = [...materialInput.options].map((opt) => opt.value);
  if (values.includes(prev)) {
    materialInput.value = prev;
  } else if (values.includes("al_6061")) {
    materialInput.value = "al_6061";
  } else if (values[0]) {
    materialInput.value = values[0];
  }
}

function labelTurnaroundOptions() {
  if (!quoteConfig) return;
  const tiers = turnaroundTiers(quoteConfig);
  for (const opt of turnaroundInput.options) {
    const tier = tiers[opt.value];
    if (!tier) continue;
    const days = tier.min_business_days;
    const title = opt.value.charAt(0).toUpperCase() + opt.value.slice(1);
    opt.textContent = `${title} (min ${days} business day${days === 1 ? "" : "s"})`;
  }
}

function readFeatureRisks() {
  return FEATURE_RISK_KEYS.filter((key) => {
    const el = form.querySelector(`input[type="checkbox"][name="feature_risks"][value="${key}"]`);
    return Boolean(el && el.checked);
  });
}

function readStockOverride() {
  const raw = [stockXInput.value, stockYInput.value, stockZInput.value].map((v) => String(v).trim());
  if (raw.every((v) => v === "")) return null;
  if (raw.some((v) => v === "")) {
    throw new Error("Stock override needs X, Y, and Z (inches) together.");
  }
  const nums = raw.map((v) => Number(v));
  if (nums.some((n) => !Number.isFinite(n) || n <= 0)) {
    throw new Error("Stock override dimensions must be > 0 inches.");
  }
  return { x: nums[0], y: nums[1], z: nums[2] };
}

function renderEstimate(result) {
  lastEstimate = result;
  if (!result) {
    estimateBox.innerHTML = `
      <h2>Shop-only rough range</h2>
      <p class="hint">Upload a STEP or STL to run the estimator. Any dollar band here is shop-only — not a final bid, and not something you accept on this page.</p>
    `;
    writeShopHiddens(null);
    return;
  }

  const geo = result.geometry;
  const env = result.envelope;
  const cost = result.cost;
  const high = result.high_side_cost;
  let statusHtml;
  let rangeHtml;

  if (result.status === "rejected") {
    statusHtml = `<p class="status-bad">OVER-TRAVEL — no customer range. RFQ can still go to quotes@ so Andrew can review.</p>`;
    rangeHtml = `<p class="range status-bad">Rejected</p>`;
  } else if (high) {
    statusHtml = `<p class="status-warn">STEP volume pending shop measurement. Shop-only high-side range — not a final bid.</p>`;
    rangeHtml = `<p class="range">${moneyText(high.quote_low_usd)} – ${moneyText(high.quote_high_usd)}</p>`;
  } else if (cost) {
    statusHtml = `<p class="status-ok">Fits 1500MX usable travel. Shop-only range — not a final bid. Andrew reviews before reply.</p>`;
    rangeHtml = `<p class="range">${moneyText(cost.quote_low_usd)} – ${moneyText(cost.quote_high_usd)}</p>`;
  } else {
    statusHtml = `<p>Waiting for geometry.</p>`;
    rangeHtml = "";
  }

  const priced = cost || high;
  const bbox = geo?.bbox_in;
  const turnaroundNote = priced?.turnaround_bumped
    ? `${priced.turnaround_applied} (requested ${priced.turnaround_requested}; auto-bumped)`
    : priced?.turnaround_applied || "—";
  const riskNote = (priced?.feature_risks || []).join(", ") || "none";
  estimateBox.innerHTML = `
    <h2>Shop-only rough range</h2>
    ${statusHtml}
    ${rangeHtml}
    <p class="hint">Shop-only range — not a final bid. Acceptance is paying the Chase link in Andrew’s bid email.</p>
    <dl>
      <dt>File</dt><dd>${geo?.filename || "—"} (${geo?.format || "—"})</dd>
      <dt>Material</dt><dd>${priced?.material_label || materialInput.value} · ${priced?.material_source || "—"}</dd>
      <dt>Turnaround</dt><dd>${turnaroundNote}</dd>
      <dt>Setups / qty</dt><dd>${priced?.setups ?? "—"} / ${priced?.qty ?? "—"}</dd>
      <dt>Tolerance</dt><dd>${priced?.tolerance_class || "—"} · complexity ${priced?.complexity_mult ?? "—"}</dd>
      <dt>Feature risks</dt><dd>${riskNote}</dd>
      <dt>BBox</dt><dd>${bbox ? `${bbox.x.toFixed(3)} × ${bbox.y.toFixed(3)} × ${bbox.z.toFixed(3)} in` : "—"}</dd>
      <dt>Part vol</dt><dd>${geo?.volume_known ? `${geo.part_volume_in3.toFixed(4)} in³` : "pending (STEP)"}</dd>
      <dt>Envelope</dt><dd>${env?.fits ? "FITS" : `OVER ${ (env?.over_travel_axes || []).map((a) => a.toUpperCase()).join(",") || "?"}`}</dd>
    </dl>
    <ul class="callouts">${(result.callouts || []).map((c) => `<li>${c}</li>`).join("")}</ul>
  `;
  writeShopHiddens(result);
}

async function recompute() {
  formError.textContent = "";
  if (!quoteConfig || !fileInput.files?.[0]) {
    renderEstimate(null);
    return;
  }
  const file = fileInput.files[0];
  try {
    detectFormat(file.name);
    if (rfqConfig && file.size > rfqConfig.maxFileBytes) {
      throw new Error(`File is over ${(rfqConfig.maxFileBytes / 1024 / 1024).toFixed(0)} MB.`);
    }
    if (!materialInput.value) {
      throw new Error("Pick a catalog material.");
    }
    const unit = unitsInput.value === "mm" ? "mm" : "inch";
    const geometry = await measureCadFile(file, unit);
    const result = estimateFromGeometry({
      config: quoteConfig,
      materialName: materialInput.value,
      geometry,
      qty: Number(qtyInput.value || 1),
      setups: Number(setupsInput.value || 1),
      materialSource: materialSourceInput.value,
      turnaround: turnaroundInput.value,
      dueDate: dueDateInput.value || null,
      toleranceClass: toleranceInput.value,
      featureRisks: readFeatureRisks(),
      stockDimsIn: readStockOverride(),
    });
    renderEstimate(result);
  } catch (err) {
    lastEstimate = null;
    formError.textContent = err.message || String(err);
    renderEstimate(null);
  }
}

function configureDelivery() {
  const local = isLocalHost(window.location.hostname);
  form.action = local ? rfqConfig.localFormAction : rfqConfig.productionFormAction;
  form.method = "POST";
  form.enctype = "multipart/form-data";
  fillHidden("_to", rfqConfig.quotesInbox);
  fillHidden("_subject", "MHL RFQ — review required before customer reply");
  fillHidden("_template", "table");
  fillHidden("_captcha", "false");
  fillHidden("_autoresponse", rfqConfig.autoresponse);
  fillHidden("_next", new URL("/thanks/", window.location.origin).href);
  const badge = document.getElementById("delivery-badge");
  if (badge) {
    badge.textContent = local
      ? `Local test inbox (no email) → ${rfqConfig.localFormAction}`
      : `Live delivery → ${rfqConfig.quotesInbox}`;
  }
}

function onSubmit(event) {
  const honey = form.elements.namedItem("company_website");
  if (honey && honey.value) {
    event.preventDefault();
    return;
  }
  if (!fileInput.files?.[0]) {
    event.preventDefault();
    formError.textContent = "Attach a STEP or STL.";
    return;
  }
  if (fileInput.files[0].size > rfqConfig.maxFileBytes) {
    event.preventDefault();
    formError.textContent = "File is too large for the email path.";
    return;
  }
  if (!lastEstimate) {
    event.preventDefault();
    formError.textContent = "Wait for the estimator to finish on the attached file.";
    return;
  }
  writeShopHiddens(lastEstimate);
  fillHidden(
    "_subject",
    `MHL RFQ — ${fileInput.files[0].name} — ${materialInput.value} ×${qtyInput.value} ${turnaroundInput.value}`
  );
}

function bindRecompute(el, eventName = "change") {
  if (el) el.addEventListener(eventName, recompute);
}

async function boot() {
  const [quoteRes, rfqRes] = await Promise.all([
    fetch("/assets/config/quote-config.json"),
    fetch("/assets/config/rfq.json"),
  ]);
  if (!quoteRes.ok || !rfqRes.ok) {
    formError.textContent = "Could not load shop config.";
    return;
  }
  quoteConfig = await quoteRes.json();
  rfqConfig = await rfqRes.json();
  enabledMaterials = listEnabledMaterials(quoteConfig);
  populateMaterialSelect("");
  labelTurnaroundOptions();
  configureDelivery();
  renderEstimate(null);
  fileInput.addEventListener("change", () => {
    if (fileInput.files?.[0]) {
      const format = (() => {
        try {
          return detectFormat(fileInput.files[0].name);
        } catch {
          return null;
        }
      })();
      if (format === "step" && unitsInput.value === "inch") {
        unitsInput.value = "mm";
      }
      if (format === "stl" && unitsInput.value === "mm") {
        unitsInput.value = "inch";
      }
    }
    recompute();
  });
  materialFilter.addEventListener("input", () => {
    populateMaterialSelect(materialFilter.value);
    recompute();
  });
  bindRecompute(materialInput);
  bindRecompute(materialSourceInput);
  bindRecompute(qtyInput);
  bindRecompute(setupsInput);
  bindRecompute(turnaroundInput);
  bindRecompute(dueDateInput);
  bindRecompute(toleranceInput);
  bindRecompute(unitsInput);
  bindRecompute(stockXInput);
  bindRecompute(stockYInput);
  bindRecompute(stockZInput);
  for (const box of form.querySelectorAll('input[type="checkbox"][name="feature_risks"]')) {
    box.addEventListener("change", recompute);
  }
  form.addEventListener("submit", onSubmit);
  submitBtn.disabled = false;
}

boot();
