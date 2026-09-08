import {
  FEATURE_RISK_KEYS,
  SHOP_HIDDEN_FIELD_KEYS,
  buildShopPayload,
  detectFormat,
  estimateFromGeometry,
  listEnabledMaterials,
  materialClassOf,
  measureCadFile,
  tightToleranceRules,
  turnaroundTiers,
} from "./estimator.js";
import { previewCadFile, resetViewer, setViewerDims } from "./viewer.js";

const form = document.getElementById("rfq-form");
const fileInput = document.getElementById("cad_file");
const materialInput = document.getElementById("material");
const materialFilter = document.getElementById("material_filter");
const materialSourceInput = document.getElementById("material_source");
const qtyInput = document.getElementById("qty");
const setupsInput = document.getElementById("setups");
const turnaroundInput = document.getElementById("turnaround");
const dueDateInput = document.getElementById("due_date");
const unitsInput = document.getElementById("units");
const stockXInput = document.getElementById("stock_x");
const stockYInput = document.getElementById("stock_y");
const stockZInput = document.getElementById("stock_z");
const tightCalloutsInput = document.getElementById("tight_callouts");
const wholePartTightInput = document.getElementById("whole_part_tight");
const blueprintInput = document.getElementById("blueprint_file");
const tightOptions = document.getElementById("tight-options");
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
      const cls = materialClassOf(spec);
      const rules = quoteConfig ? tightToleranceRules(quoteConfig) : null;
      opt.dataset.class = cls;
      if (rules) {
        opt.dataset.standard = String(
          cls === "plastic" ? rules.standard_in_plastic : rules.standard_in_metal
        );
      }
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
  const hint = document.getElementById("turnaround-rate-hint");
  const rushRate = Number(quoteConfig.shop && quoteConfig.shop.rush_rate_usd_per_hr);
  if (hint && Number.isFinite(rushRate) && rushRate > 0) {
    hint.textContent =
      `Required. A tight due date can auto-bump this for the shop range. ` +
      `Rush and emergency bill labor at $${rushRate}/hr.`;
  }
}

function readToleranceClass() {
  const el = form.querySelector('input[type="radio"][name="tolerance_class"]:checked');
  return el ? el.value : "standard";
}

function needsBlueprint() {
  return readToleranceClass() === "tight";
}

function syncTolerance() {
  const tight = readToleranceClass() === "tight";
  if (tightOptions) tightOptions.hidden = !tight;
  if (blueprintInput) {
    blueprintInput.required = tight;
    if (!tight) blueprintInput.value = "";
  }
  if (!tight && wholePartTightInput) wholePartTightInput.checked = false;
  if (!tight && tightCalloutsInput) tightCalloutsInput.value = "0";
}

function syncMaterialHint() {
  const hint = document.getElementById("standard-tol-hint");
  if (!hint || !materialInput) return;
  const opt = materialInput.options[materialInput.selectedIndex];
  if (!opt || !opt.value) {
    hint.textContent = "";
    return;
  }
  const cls = opt.dataset.class || "metal";
  const std = opt.dataset.standard;
  if (!std) {
    hint.textContent = "";
    return;
  }
  hint.textContent = `Standard quality for ${cls}: ±${std}" — tighter than this is "tight".`;
}

function readTightCallouts() {
  if (readToleranceClass() !== "tight") return 0;
  if (wholePartTightInput && wholePartTightInput.checked) return 0;
  const n = Number(tightCalloutsInput && tightCalloutsInput.value);
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : 0;
}

function readWholePartTight() {
  return readToleranceClass() === "tight" && Boolean(wholePartTightInput && wholePartTightInput.checked);
}

function readQuestionnaire() {
  return {
    material_cert: Boolean(form.querySelector('input[name="material_cert"]:checked')),
    tapped_holes: Boolean(form.querySelector('input[name="tapped_holes"]:checked')),
    part_marking: Boolean(form.querySelector('input[name="part_marking"]:checked')),
  };
}

function extrasLabel(extras) {
  const bits = [];
  if (extras.material_cert) bits.push("material cert");
  if (extras.tapped_holes) bits.push("tapped/threaded holes");
  if (extras.part_marking) bits.push("part marking");
  return bits.join(", ") || "none";
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

function customerCallouts(callouts) {
  return (callouts || []).filter((raw) => {
    const lower = String(raw).toLowerCase();
    return !lower.includes("shop-only");
  });
}

function renderEstimate(result) {
  lastEstimate = result;
  if (!result) {
    estimateBox.innerHTML = `
      <h2>Estimate range</h2>
      <p class="hint">This is an estimate — not a final bid.</p>
    `;
    writeShopHiddens(null);
    fillHidden("material_cert", "");
    fillHidden("tapped_holes", "");
    fillHidden("part_marking", "");
    fillHidden("blueprint_attached", "");
    return;
  }

  const geo = result.geometry;
  const env = result.envelope;
  const cost = result.cost;
  const high = result.high_side_cost;
  let statusHtml;
  let rangeHtml;

  if (result.status === "rejected") {
    statusHtml = `<p class="status-bad">OVER-TRAVEL — no customer range. RFQ can still go to quotes@ so the shop can review.</p>`;
    rangeHtml = `<p class="range status-bad">Rejected</p>`;
  } else if (high) {
    statusHtml = `<p class="status-warn">STEP volume pending shop measurement. High-side estimate — not a final bid.</p>`;
    rangeHtml = `<p class="range">${moneyText(high.quote_low_usd)} – ${moneyText(high.quote_high_usd)}</p>`;
  } else if (cost) {
    statusHtml = `<p class="status-ok">Fits usable travel. Estimate range — not a final bid. The shop confirms from quotes@.</p>`;
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
  const extras = readQuestionnaire();
  const perPartHtml =
    priced && priced.qty > 1 && priced.per_part_low_usd != null
      ? `<p class="range-sub">≈ ${moneyText(priced.per_part_low_usd)} – ${moneyText(priced.per_part_high_usd)} per part</p>`
      : "";
  let toleranceNote = priced?.tolerance_class || "—";
  if (priced?.whole_part_tight) toleranceNote += " (whole part tight)";
  else if (priced?.tight_callouts) {
    toleranceNote += ` (${priced.tight_callouts} callout${priced.tight_callouts === 1 ? "" : "s"})`;
  }
  if (priced?.complexity_mult != null) toleranceNote += ` · complexity ${priced.complexity_mult}`;
  const driverNotes = [];
  if (priced?.whole_part_tight) {
    driverNotes.push(
      "Whole part is tight tolerance: per-callout adders do not apply; labor uses the rush shop rate."
    );
  } else if (priced?.tight_callouts >= 1) {
    driverNotes.push(
      `${priced.tight_callouts} tight-tolerance callout(s): +${moneyText(priced.tolerance_labor_usd)} labor per part. Attach a blueprint so the shop can verify.`
    );
  }
  if (priced?.guardrail_callout) driverNotes.push(priced.guardrail_callout);
  const allCallouts = [...customerCallouts(result.callouts), ...driverNotes];
  estimateBox.innerHTML = `
    <h2>Estimate range</h2>
    ${statusHtml}
    ${rangeHtml}
    ${perPartHtml}
    <p class="hint">This is an estimate — not a final bid. The shop confirms from quotes@ after you proceed. A payment link arrives in that email.</p>
    <dl>
      <dt>File</dt><dd>${geo?.filename || "—"} (${geo?.format || "—"})</dd>
      <dt>Material</dt><dd>${priced?.material_label || materialInput.value} · ${priced?.material_source || "—"}</dd>
      <dt>Turnaround</dt><dd>${turnaroundNote}</dd>
      <dt>Setups / qty</dt><dd>${priced?.setups ?? "—"} / ${priced?.qty ?? "—"}</dd>
      <dt>Tolerance</dt><dd>${toleranceNote}</dd>
      <dt>Also requested</dt><dd>${extrasLabel(extras)}</dd>
      <dt>Feature risks</dt><dd>${riskNote}</dd>
      <dt>BBox</dt><dd>${bbox ? `${bbox.x.toFixed(3)} × ${bbox.y.toFixed(3)} × ${bbox.z.toFixed(3)} in` : "—"}</dd>
      <dt>Part vol</dt><dd>${geo?.volume_known ? `${geo.part_volume_in3.toFixed(4)} in³` : "pending (STEP)"}</dd>
      <dt>Envelope</dt><dd>${env?.fits ? "FITS" : `OVER ${ (env?.over_travel_axes || []).map((a) => a.toUpperCase()).join(",") || "?"}`}</dd>
    </dl>
    <ul class="callouts">${allCallouts.map((c) => `<li>${c}</li>`).join("")}</ul>
  `;
  writeShopHiddens(result);
  fillHidden("material_cert", extras.material_cert ? "yes" : "no");
  fillHidden("tapped_holes", extras.tapped_holes ? "yes" : "no");
  fillHidden("part_marking", extras.part_marking ? "yes" : "no");
  fillHidden(
    "blueprint_attached",
    blueprintInput && blueprintInput.files && blueprintInput.files[0] ? "yes" : "no"
  );
  if (bbox) setViewerDims(bbox, geo?.format);
}

async function recompute() {
  formError.textContent = "";
  if (!quoteConfig || !fileInput.files?.[0]) {
    renderEstimate(null);
    if (!fileInput.files?.[0]) resetViewer();
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
      toleranceClass: readToleranceClass(),
      featureRisks: readFeatureRisks(),
      stockDimsIn: readStockOverride(),
      tightCallouts: readTightCallouts(),
      wholePartTight: readWholePartTight(),
    });
    setViewerDims(geometry.bbox_in, geometry.format);
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
  if (needsBlueprint() && !(blueprintInput && blueprintInput.files && blueprintInput.files[0])) {
    event.preventDefault();
    formError.textContent = "A blueprint / drawing is required whenever tight tolerance is requested.";
    return;
  }
  writeShopHiddens(lastEstimate);
  const extras = readQuestionnaire();
  fillHidden("material_cert", extras.material_cert ? "yes" : "no");
  fillHidden("tapped_holes", extras.tapped_holes ? "yes" : "no");
  fillHidden("part_marking", extras.part_marking ? "yes" : "no");
  fillHidden(
    "blueprint_attached",
    blueprintInput && blueprintInput.files && blueprintInput.files[0] ? "yes" : "no"
  );
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
  syncMaterialHint();
  syncTolerance();
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
      const unit = unitsInput.value === "mm" ? "mm" : "inch";
      previewCadFile(fileInput.files[0], unit);
    } else {
      resetViewer();
    }
    recompute();
  });
  materialFilter.addEventListener("input", () => {
    populateMaterialSelect(materialFilter.value);
    syncMaterialHint();
    recompute();
  });
  bindRecompute(materialInput);
  materialInput.addEventListener("change", syncMaterialHint);
  bindRecompute(materialSourceInput);
  bindRecompute(qtyInput);
  bindRecompute(setupsInput);
  bindRecompute(turnaroundInput);
  bindRecompute(dueDateInput);
  bindRecompute(unitsInput);
  bindRecompute(tightCalloutsInput);
  if (wholePartTightInput) {
    wholePartTightInput.addEventListener("change", () => {
      if (tightCalloutsInput) {
        tightCalloutsInput.disabled = wholePartTightInput.checked;
        if (wholePartTightInput.checked) tightCalloutsInput.value = "0";
      }
      recompute();
    });
  }
  if (blueprintInput) blueprintInput.addEventListener("change", recompute);
  for (const box of form.querySelectorAll(
    'input[type="checkbox"][name="material_cert"], input[type="checkbox"][name="tapped_holes"], input[type="checkbox"][name="part_marking"]'
  )) {
    box.addEventListener("change", recompute);
  }
  for (const radio of form.querySelectorAll('input[type="radio"][name="tolerance_class"]')) {
    radio.addEventListener("change", () => {
      syncTolerance();
      recompute();
    });
  }
  unitsInput.addEventListener("change", () => {
    if (fileInput.files?.[0]) {
      previewCadFile(fileInput.files[0], unitsInput.value === "mm" ? "mm" : "inch");
    }
  });
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
