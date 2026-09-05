import { detectFormat, estimateFromGeometry, measureCadFile } from "./estimator.js";

const form = document.getElementById("rfq-form");
const fileInput = document.getElementById("cad_file");
const materialInput = document.getElementById("material");
const qtyInput = document.getElementById("qty");
const unitsInput = document.getElementById("units");
const estimateBox = document.getElementById("estimate-panel");
const formError = document.getElementById("form-error");
const submitBtn = document.getElementById("submit-rfq");

let quoteConfig = null;
let rfqConfig = null;
let lastEstimate = null;

function isLocalHost(hostname) {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "[::1]";
}

function moneyText(value) {
  return `$${Number(value).toFixed(2)}`;
}

function fillHidden(name, value) {
  const el = form.elements.namedItem(name);
  if (el) el.value = value == null ? "" : String(value);
}

function renderEstimate(result) {
  lastEstimate = result;
  if (!result) {
    estimateBox.innerHTML = `
      <h2>Shop-only rough range</h2>
      <p class="hint">Upload a STEP or STL to run the estimator. Any dollar band here is shop-only — not a final bid, and not something you accept on this page.</p>
    `;
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

  const bbox = geo?.bbox_in;
  estimateBox.innerHTML = `
    <h2>Shop-only rough range</h2>
    ${statusHtml}
    ${rangeHtml}
    <p class="hint">Shop-only range — not a final bid. Acceptance is paying the Chase link in Andrew’s bid email.</p>
    <dl>
      <dt>File</dt><dd>${geo?.filename || "—"} (${geo?.format || "—"})</dd>
      <dt>BBox</dt><dd>${bbox ? `${bbox.x.toFixed(3)} × ${bbox.y.toFixed(3)} × ${bbox.z.toFixed(3)} in` : "—"}</dd>
      <dt>Part vol</dt><dd>${geo?.volume_known ? `${geo.part_volume_in3.toFixed(4)} in³` : "pending (STEP)"}</dd>
      <dt>Envelope</dt><dd>${env?.fits ? "FITS" : `OVER ${ (env?.over_travel_axes || []).map((a) => a.toUpperCase()).join(",") || "?"}`}</dd>
    </dl>
    <ul class="callouts">${(result.callouts || []).map((c) => `<li>${c}</li>`).join("")}</ul>
  `;
  writeEstimateFields(result);
}

function writeEstimateFields(result) {
  const geo = result.geometry || {};
  const bbox = geo.bbox_in || {};
  const env = result.envelope || {};
  const cost = result.cost || result.high_side_cost;
  fillHidden("estimator_status", result.status);
  fillHidden("envelope_fits", env.fits ? "yes" : "no");
  fillHidden("over_travel_axes", (env.over_travel_axes || []).join(","));
  fillHidden("bbox_x_in", bbox.x != null ? bbox.x.toFixed(4) : "");
  fillHidden("bbox_y_in", bbox.y != null ? bbox.y.toFixed(4) : "");
  fillHidden("bbox_z_in", bbox.z != null ? bbox.z.toFixed(4) : "");
  fillHidden("part_volume_in3", geo.volume_known ? String(geo.part_volume_in3) : "pending_step");
  fillHidden("cad_format", geo.format || "");
  fillHidden(
    "quote_range_usd",
    cost ? `${cost.quote_low_usd.toFixed(2)}-${cost.quote_high_usd.toFixed(2)}` : "none"
  );
  fillHidden("quote_low_usd", cost ? cost.quote_low_usd.toFixed(2) : "");
  fillHidden("quote_high_usd", cost ? cost.quote_high_usd.toFixed(2) : "");
  fillHidden("raw_quote_usd", cost ? cost.raw_quote_usd.toFixed(2) : "");
  fillHidden("labor_usd", cost ? cost.labor_usd.toFixed(2) : "");
  fillHidden("material_usd", cost ? cost.material_usd.toFixed(2) : "");
  fillHidden("removal_volume_in3", cost ? String(cost.removal_volume_in3) : "");
  fillHidden("cut_hours", cost ? String(cost.cut_hours) : "");
  fillHidden("setup_hours", cost ? String(cost.setup_hours) : "");
  fillHidden("step_volume_pending", geo.volume_known ? "no" : "yes");
  fillHidden("high_side_estimate", result.high_side_cost ? "yes" : "no");
  fillHidden(
    "rejection_reasons",
    (result.rejection_reasons || []).join(" | ")
  );
  fillHidden(
    "shop_review_required",
    "YES — do not send this range to the customer until Andrew approves."
  );
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
    const unit = unitsInput.value === "mm" ? "mm" : "inch";
    const geometry = await measureCadFile(file, unit);
    const result = estimateFromGeometry({
      config: quoteConfig,
      materialName: materialInput.value,
      geometry,
      qty: Number(qtyInput.value || 1),
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
  fillHidden(
    "_subject",
    `MHL RFQ — ${fileInput.files[0].name} — ${materialInput.value} ×${qtyInput.value}`
  );
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
  materialInput.addEventListener("change", recompute);
  qtyInput.addEventListener("change", recompute);
  unitsInput.addEventListener("change", recompute);
  form.addEventListener("submit", onSubmit);
  submitBtn.disabled = false;
}

boot();
