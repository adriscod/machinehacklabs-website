/**
 * Browser/Node port of the MHL-CF-001 / RFQ v2 cost model + STL/STEP geometry.
 * Keep rounding and formulas aligned with mhl-quote/mhl_quote/cost.py.
 *
 * Additive v2 inputs (UI teammate wires these on /quote/):
 *   materialSource, turnaround, dueDate, setups, toleranceClass,
 *   featureRisks, stockDimsIn. See RFQ_V2_UI_INPUTS and buildShopPayload().
 */

export const MM_PER_INCH = 25.4;
export const IN3_PER_MM3 = 1 / MM_PER_INCH ** 3;

export function money(value) {
  return Math.round((Number(value) + 0) * 100) / 100;
}

export function hours(value) {
  return Math.round(Number(value) * 10000) / 10000;
}

export function volume(value) {
  return Math.round(Number(value) * 10000) / 10000;
}

export function linearToInches(value, unit) {
  if (unit === "inch") return Number(value);
  if (unit === "mm") return Number(value) / MM_PER_INCH;
  throw new Error(`unhandled length unit: ${unit}`);
}

export function volumeToIn3(value, unit) {
  if (unit === "inch") return Number(value);
  if (unit === "mm") return Number(value) * IN3_PER_MM3;
  throw new Error(`unhandled length unit: ${unit}`);
}

export function vecVolume(vec) {
  return Math.max(0, vec.x) * Math.max(0, vec.y) * Math.max(0, vec.z);
}

export function usableTravel(machine) {
  const e = machine.envelope_in;
  const m = machine.fixture_margin_in;
  return {
    x: e.x - m.x,
    y: e.y - m.y,
    z: e.z - m.z,
  };
}

export function materialIsEnabled(spec) {
  return spec && spec.enabled !== false;
}

export function listEnabledMaterials(config) {
  return Object.entries(config.materials || {})
    .filter(([, spec]) => materialIsEnabled(spec))
    .map(([key, spec]) => ({ key, ...spec }));
}

export function findMaterial(config, name) {
  const needle = String(name).trim().toLowerCase();
  const materials = config.materials || {};
  if (materials[needle]) {
    if (!materialIsEnabled(materials[needle])) {
      throw new Error(`material ${name} is disabled in the catalog`);
    }
    return { key: needle, ...materials[needle] };
  }
  const aliasHits = [];
  const familyHits = [];
  for (const [key, spec] of Object.entries(materials)) {
    if (!materialIsEnabled(spec)) continue;
    const aliases = (spec.aliases || []).map((a) => String(a).toLowerCase());
    if (aliases.includes(needle)) aliasHits.push({ key, ...spec });
    if (needle === String(spec.family || "").toLowerCase()) familyHits.push({ key, ...spec });
  }
  if (aliasHits.length === 1) return aliasHits[0];
  if (aliasHits.length > 1) {
    throw new Error(`material alias ${name} is ambiguous; matches ${aliasHits.map((s) => s.key).join(", ")}`);
  }
  if (familyHits.length === 1) return familyHits[0];
  if (familyHits.length > 1) {
    throw new Error(
      `material family ${name} is ambiguous; pick a catalog key: ${familyHits.map((s) => s.key).join(", ")}`
    );
  }
  throw new Error(`unknown material ${name}`);
}

export const MATERIAL_SOURCES = ["shop_buys", "customer_supplied"];
export const TURNAROUND_TIERS = ["standard", "rush", "emergency"];
export const TOLERANCE_CLASSES = ["standard", "tight", "precision"];
export const FEATURE_RISK_KEYS = ["deep_pockets", "thin_walls", "fine_engraving", "many_holes"];

export const SHOP_HIDDEN_FIELD_KEYS = [
  "material_key",
  "material_family",
  "material_source",
  "turnaround",
  "turnaround_requested",
  "turnaround_bumped",
  "rush_labor_mult",
  "rush_setup_mult",
  "setups",
  "qty",
  "tolerance_class",
  "complexity_mult",
  "feature_risks",
  "due_date",
  "due_date_business_days",
  "due_date_warning",
  "shop_review_required",
  "shop_review_reasons",
  "catalog_values_are_placeholders",
  "stock_x_in",
  "stock_y_in",
  "stock_z_in",
  "stock_override",
];

/** Inputs the /quote/ UI teammate should collect and pass into estimateFromGeometry. */
export const RFQ_V2_UI_INPUTS = {
  material: "catalog key (al_6061, steel_1018, …). aluminum/steel aliases still resolve.",
  material_source: "shop_buys | customer_supplied",
  turnaround: "standard | rush | emergency (required)",
  due_date: "YYYY-MM-DD; not price-inert — can auto-bump turnaround",
  setups: "integer >= 1, default 1",
  tolerance_class: "standard | tight | precision (required)",
  feature_risks: "optional multi: deep_pockets, thin_walls, fine_engraving, many_holes",
  stock_x_in: "optional stock override inches (all three required together)",
  stock_y_in: "optional stock override inches",
  stock_z_in: "optional stock override inches",
};

const TURNAROUND_RANK = { standard: 0, rush: 1, emergency: 2 };

function defaultTurnaroundTiers() {
  return {
    standard: { labor_mult: 1.0, setup_mult: 1.0, min_business_days: 10 },
    rush: { labor_mult: 1.5, setup_mult: 1.25, min_business_days: 4 },
    emergency: { labor_mult: 2.0, setup_mult: 1.5, min_business_days: 1 },
  };
}

export function turnaroundTiers(config) {
  const raw = config.turnaround || {};
  const defaults = defaultTurnaroundTiers();
  const out = {};
  for (const key of TURNAROUND_TIERS) {
    const row = raw[key] || {};
    out[key] = {
      labor_mult: Number(row.labor_mult ?? defaults[key].labor_mult),
      setup_mult: Number(row.setup_mult ?? defaults[key].setup_mult),
      min_business_days: Number(row.min_business_days ?? defaults[key].min_business_days),
    };
  }
  return out;
}

export function parseMaterialSource(value) {
  if (value == null || value === "") return "shop_buys";
  const needle = String(value).trim().toLowerCase();
  if (!MATERIAL_SOURCES.includes(needle)) {
    throw new Error(`unknown material_source ${value}`);
  }
  return needle;
}

export function parseTurnaround(value) {
  if (value == null || value === "") return "standard";
  const needle = String(value).trim().toLowerCase();
  if (!TURNAROUND_TIERS.includes(needle)) {
    throw new Error(`unknown turnaround ${value}`);
  }
  return needle;
}

export function parseToleranceClass(value) {
  if (value == null || value === "") return "standard";
  const needle = String(value).trim().toLowerCase();
  if (!TOLERANCE_CLASSES.includes(needle)) {
    throw new Error(`unknown tolerance_class ${value}`);
  }
  return needle;
}

export function parseFeatureRisks(values, allowed = FEATURE_RISK_KEYS) {
  if (!values || values.length === 0) return [];
  const allow = new Set(allowed);
  const out = [];
  const seen = new Set();
  for (const raw of values) {
    const needle = String(raw).trim().toLowerCase();
    if (!allow.has(needle)) throw new Error(`unknown feature_risk ${raw}`);
    if (!seen.has(needle)) {
      out.push(needle);
      seen.add(needle);
    }
  }
  return out;
}

export function parseIsoDate(value) {
  if (value == null || value === "") return null;
  const text = String(value).trim().slice(0, 10);
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text);
  if (!match) throw new Error(`invalid ISO date ${value}`);
  return { y: Number(match[1]), m: Number(match[2]), d: Number(match[3]), iso: text };
}

function dateUtc(parts) {
  return Date.UTC(parts.y, parts.m - 1, parts.d);
}

export function businessDaysUntil(asOf, due) {
  const start = dateUtc(asOf);
  const end = dateUtc(due);
  if (end <= start) return 0;
  let days = 0;
  let cursor = start + 24 * 60 * 60 * 1000;
  while (cursor <= end) {
    const weekday = new Date(cursor).getUTCDay();
    if (weekday !== 0 && weekday !== 6) days += 1;
    cursor += 24 * 60 * 60 * 1000;
  }
  return days;
}

export function impliedTurnaround(businessDays, tiers) {
  if (businessDays >= tiers.standard.min_business_days) return "standard";
  if (businessDays >= tiers.rush.min_business_days) return "rush";
  return "emergency";
}

export function resolveTurnaround({ config, requested, dueDate, asOfDate }) {
  const tiers = turnaroundTiers(config);
  const req = parseTurnaround(requested);
  if (!dueDate) {
    return { applied: req, bumped: false, businessDays: null, warning: null, reviewReasons: [] };
  }
  const due = typeof dueDate === "string" ? parseIsoDate(dueDate) : dueDate;
  const asOf = asOfDate
    ? typeof asOfDate === "string"
      ? parseIsoDate(asOfDate)
      : asOfDate
    : todayUtcParts();
  const days = businessDaysUntil(asOf, due);
  const implied = impliedTurnaround(days, tiers);
  let applied = req;
  let bumped = false;
  let warning = null;
  const reviewReasons = [];
  if (dateUtc(due) <= dateUtc(asOf)) {
    warning =
      `due_date ${due.iso} is on or before as-of ${asOf.iso}; treating as emergency and requiring shop review.`;
    if (TURNAROUND_RANK[req] < TURNAROUND_RANK.emergency) {
      applied = "emergency";
      bumped = true;
    }
    reviewReasons.push(warning);
    return { applied, bumped, businessDays: days, warning, reviewReasons };
  }
  if (TURNAROUND_RANK[implied] > TURNAROUND_RANK[req]) {
    applied = implied;
    bumped = true;
    warning =
      `due_date ${due.iso} is ${days} business day(s) from ${asOf.iso}, which is tighter than turnaround ` +
      `${req} (min ${tiers[req].min_business_days} business days). Auto-bumped to ${applied}.`;
    reviewReasons.push(warning);
  }
  return { applied, bumped, businessDays: days, warning, reviewReasons };
}

function todayUtcParts() {
  const now = new Date();
  return {
    y: now.getUTCFullYear(),
    m: now.getUTCMonth() + 1,
    d: now.getUTCDate(),
    iso: now.toISOString().slice(0, 10),
  };
}

export function complexityMult({ config, toleranceClass, featureRisks = [] }) {
  const tol = (config.tolerance || {})[toleranceClass] ?? { standard: 1, tight: 1.25, precision: 1.5 }[toleranceClass];
  const each = Number((config.feature_risks && config.feature_risks.mult_each) ?? 0.15);
  const cap = Number((config.feature_risks && config.feature_risks.mult_cap) ?? 1.75);
  return Math.min(cap, Number(tol) + featureRisks.length * each);
}

export function isPlaceholderFlag(value) {
  if (value == null) return true;
  if (typeof value === "boolean") return value;
  return String(value).trim().toUpperCase() === "TODO_REPLACE";
}

export function computeCost({ config, material, bboxIn, partVolumeIn3, overrides = {} }) {
  const qty = overrides.qty == null ? 1 : Number(overrides.qty);
  if (qty < 1 || !Number.isFinite(qty)) throw new Error("qty must be >= 1");
  const setups = overrides.setups == null ? 1 : Number(overrides.setups);
  if (setups < 1 || !Number.isFinite(setups)) throw new Error("setups must be >= 1");

  const stock = overrides.stockDimsIn || bboxIn;
  const stockVol = Math.max(0, vecVolume(stock));
  const partVol = Math.max(0, Number(partVolumeIn3) || 0);
  const removalVol = Math.max(0, stockVol - partVol);

  const mrr = overrides.mrrEffIn3PerHr == null ? material.mrr_eff_in3_per_hr : overrides.mrrEffIn3PerHr;
  if (mrr <= 0) throw new Error("MRR_eff must be > 0");

  const materialSource = parseMaterialSource(overrides.materialSource);
  const requestedTurnaround = parseTurnaround(overrides.turnaround);
  const toleranceClass = parseToleranceClass(overrides.toleranceClass);
  const allowedRisks = (config.feature_risks && config.feature_risks.keys) || FEATURE_RISK_KEYS;
  const featureRisks = parseFeatureRisks(overrides.featureRisks || [], allowedRisks);

  const schedule = resolveTurnaround({
    config,
    requested: requestedTurnaround,
    dueDate: overrides.dueDate,
    asOfDate: overrides.asOfDate,
  });
  const tiers = turnaroundTiers(config);
  const rushLabor = tiers[schedule.applied].labor_mult;
  const rushSetup = tiers[schedule.applied].setup_mult;

  const baseSetup = overrides.setupHours == null ? config.shop.setup_hours : overrides.setupHours;
  if (baseSetup < 0) throw new Error("setup_hours must be >= 0");
  const setup = baseSetup * setups * rushSetup;

  const complexity = complexityMult({ config, toleranceClass, featureRisks });
  const cutEach = removalVol === 0 ? 0 : removalVol / mrr;
  const cut = cutEach * qty * complexity;
  const labor = (setup + cut) * config.shop.rate_usd_per_hr * rushLabor;

  let materialUsd;
  let catalogEstimate;
  if (materialSource === "customer_supplied") {
    materialUsd = 0;
    catalogEstimate = false;
  } else if (overrides.stockPurchaseCostUsd != null) {
    materialUsd = Number(overrides.stockPurchaseCostUsd);
    catalogEstimate = false;
  } else {
    materialUsd = stockVol * material.cost_usd_per_in3 * qty;
    catalogEstimate = true;
  }

  const minCharge = config.shop.min_charge_usd * rushLabor;
  const raw = money(Math.max(materialUsd + labor, minCharge));
  const reviewReasons = [...schedule.reviewReasons];
  const precisionNeedsReview = config.tolerance?.precision_requires_shop_review !== false;
  if (toleranceClass === "precision" && precisionNeedsReview) {
    reviewReasons.push("precision tolerance class requires shop review before any customer reply.");
  }
  const placeholders =
    isPlaceholderFlag(material.cost_placeholder) || isPlaceholderFlag(material.mrr_placeholder);

  return {
    material_key: material.key,
    material_label: material.label,
    material_family: material.family || "",
    material_source: materialSource,
    qty,
    setups,
    stock_volume_in3: volume(stockVol),
    part_volume_in3: volume(partVol),
    removal_volume_in3: volume(removalVol),
    setup_hours: hours(setup),
    cut_hours: hours(cut),
    mrr_eff_in3_per_hr: mrr,
    shop_rate_usd_per_hr: config.shop.rate_usd_per_hr,
    labor_usd: money(labor),
    material_usd: money(materialUsd),
    material_cost_is_catalog_estimate: catalogEstimate,
    catalog_values_are_placeholders: placeholders,
    raw_quote_usd: raw,
    quote_low_usd: money(raw * config.shop.band_low),
    quote_high_usd: money(raw * config.shop.band_high),
    min_charge_applied: materialUsd + labor < minCharge,
    turnaround_requested: requestedTurnaround,
    turnaround_applied: schedule.applied,
    turnaround_bumped: schedule.bumped,
    rush_labor_mult: rushLabor,
    rush_setup_mult: rushSetup,
    tolerance_class: toleranceClass,
    feature_risks: featureRisks,
    complexity_mult: complexity,
    due_date: overrides.dueDate || null,
    due_date_business_days: schedule.businessDays,
    due_date_warning: schedule.warning,
    shop_review_required: reviewReasons.length > 0,
    shop_review_reasons: reviewReasons,
  };
}

export function checkEnvelope(machine, stockIn) {
  const usable = usableTravel(machine);
  const over = [];
  if (stockIn.x > usable.x + 1e-9) over.push("x");
  if (stockIn.y > usable.y + 1e-9) over.push("y");
  if (stockIn.z > usable.z + 1e-9) over.push("z");

  let rotationWouldFit = false;
  let rotationNote = null;
  if (over.length) {
    const dims = [stockIn.x, stockIn.y, stockIn.z];
    const perms = [
      [dims[0], dims[1], dims[2]],
      [dims[0], dims[2], dims[1]],
      [dims[1], dims[0], dims[2]],
      [dims[1], dims[2], dims[0]],
      [dims[2], dims[0], dims[1]],
      [dims[2], dims[1], dims[0]],
    ];
    for (const perm of perms) {
      if (perm[0] <= usable.x + 1e-9 && perm[1] <= usable.y + 1e-9 && perm[2] <= usable.z + 1e-9) {
        rotationWouldFit = true;
        rotationNote =
          `As-imported stock is over travel, but a 90° axis remapping ` +
          `(${perm[0].toFixed(3)} × ${perm[1].toFixed(3)} × ${perm[2].toFixed(3)} in) would fit ` +
          `usable ${usable.x.toFixed(3)} × ${usable.y.toFixed(3)} × ${usable.z.toFixed(3)} in. ` +
          `Quote is still rejected for the as-imported orientation.`;
        break;
      }
    }
    if (!rotationWouldFit) {
      rotationNote = "No 90° axis remapping fits the 1500MX usable travel.";
    }
  }

  return {
    fits: over.length === 0,
    usable_in: usable,
    stock_in: stockIn,
    over_travel_axes: over,
    rotation_would_fit: rotationWouldFit,
    rotation_note: rotationNote,
  };
}

export function envelopeReasons(machine, check) {
  if (check.fits) return [];
  const bits = check.over_travel_axes.map((axis) => {
    const stock = check.stock_in[axis];
    const usable = check.usable_in[axis];
    return `${axis.toUpperCase()} stock ${stock.toFixed(3)} in > usable ${usable.toFixed(3)} in`;
  });
  return [
    `REJECTED: stock exceeds ${machine.name} usable travel (envelope minus fixture margin): ${bits.join("; ")}.`,
  ];
}

export function detectFormat(filename) {
  const lower = String(filename).toLowerCase();
  if (lower.endsWith(".step") || lower.endsWith(".stp")) return "step";
  if (lower.endsWith(".stl")) return "stl";
  throw new Error("Upload a .step/.stp or .stl file.");
}

export function measureStlBuffer(buffer, unit) {
  const bytes = buffer instanceof ArrayBuffer ? new Uint8Array(buffer) : new Uint8Array(buffer);
  const asciiProbe = new TextDecoder("latin1").decode(bytes.subarray(0, Math.min(bytes.length, 80)));
  const looksAscii = /^\s*solid\b/i.test(asciiProbe) && !hasBinaryStlTriangleCount(bytes);
  const mesh = looksAscii && !isBinaryStl(bytes) ? parseAsciiStl(bytes) : parseBinaryStl(bytes);
  return {
    format: "stl",
    bbox_in: {
      x: linearToInches(mesh.bbox.x, unit),
      y: linearToInches(mesh.bbox.y, unit),
      z: linearToInches(mesh.bbox.z, unit),
    },
    part_volume_in3: volumeToIn3(Math.abs(mesh.volume), unit),
    volume_known: true,
    notes: mesh.volume === 0 ? ["STL solid volume is ~0. Mesh may not be watertight."] : [],
  };
}

function hasBinaryStlTriangleCount(bytes) {
  if (bytes.length < 84) return false;
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const count = view.getUint32(80, true);
  return 84 + count * 50 === bytes.length;
}

function isBinaryStl(bytes) {
  if (bytes.length < 84) return false;
  if (hasBinaryStlTriangleCount(bytes)) return true;
  const head = new TextDecoder("latin1").decode(bytes.subarray(0, 5)).toLowerCase();
  return head !== "solid";
}

function parseBinaryStl(bytes) {
  if (bytes.length < 84) throw new Error("STL file is too small to be a mesh.");
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const count = view.getUint32(80, true);
  let offset = 84;
  let volume = 0;
  let minX = Infinity;
  let minY = Infinity;
  let minZ = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  let maxZ = -Infinity;
  for (let i = 0; i < count; i += 1) {
    if (offset + 50 > bytes.length) break;
    const ax = view.getFloat32(offset + 12, true);
    const ay = view.getFloat32(offset + 16, true);
    const az = view.getFloat32(offset + 20, true);
    const bx = view.getFloat32(offset + 24, true);
    const by = view.getFloat32(offset + 28, true);
    const bz = view.getFloat32(offset + 32, true);
    const cx = view.getFloat32(offset + 36, true);
    const cy = view.getFloat32(offset + 40, true);
    const cz = view.getFloat32(offset + 44, true);
    volume += signedTetVolume(ax, ay, az, bx, by, bz, cx, cy, cz);
    minX = Math.min(minX, ax, bx, cx);
    minY = Math.min(minY, ay, by, cy);
    minZ = Math.min(minZ, az, bz, cz);
    maxX = Math.max(maxX, ax, bx, cx);
    maxY = Math.max(maxY, ay, by, cy);
    maxZ = Math.max(maxZ, az, bz, cz);
    offset += 50;
  }
  if (!Number.isFinite(minX)) throw new Error("STL has no triangles.");
  return {
    volume,
    bbox: { x: maxX - minX, y: maxY - minY, z: maxZ - minZ },
  };
}

function parseAsciiStl(bytes) {
  const text = new TextDecoder("utf-8").decode(bytes);
  const verts = [];
  const vertexRe = /vertex\s+([+\-0-9.eE]+)\s+([+\-0-9.eE]+)\s+([+\-0-9.eE]+)/g;
  let match;
  while ((match = vertexRe.exec(text)) !== null) {
    verts.push([Number(match[1]), Number(match[2]), Number(match[3])]);
  }
  if (verts.length < 3) throw new Error("STL has no triangles.");
  let volume = 0;
  let minX = Infinity;
  let minY = Infinity;
  let minZ = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  let maxZ = -Infinity;
  for (let i = 0; i + 2 < verts.length; i += 3) {
    const a = verts[i];
    const b = verts[i + 1];
    const c = verts[i + 2];
    volume += signedTetVolume(a[0], a[1], a[2], b[0], b[1], b[2], c[0], c[1], c[2]);
    minX = Math.min(minX, a[0], b[0], c[0]);
    minY = Math.min(minY, a[1], b[1], c[1]);
    minZ = Math.min(minZ, a[2], b[2], c[2]);
    maxX = Math.max(maxX, a[0], b[0], c[0]);
    maxY = Math.max(maxY, a[1], b[1], c[1]);
    maxZ = Math.max(maxZ, a[2], b[2], c[2]);
  }
  return {
    volume,
    bbox: { x: maxX - minX, y: maxY - minY, z: maxZ - minZ },
  };
}

function signedTetVolume(ax, ay, az, bx, by, bz, cx, cy, cz) {
  return (
    (ax * (by * cz - bz * cy) - ay * (bx * cz - bz * cx) + az * (bx * cy - by * cx)) / 6
  );
}

export function measureStepText(text, unit) {
  const pointRe = /CARTESIAN_POINT\s*\(\s*'[^']*'\s*,\s*\(\s*([^)]+?)\s*\)/gi;
  let minX = Infinity;
  let minY = Infinity;
  let minZ = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  let maxZ = -Infinity;
  let count = 0;
  let match;
  while ((match = pointRe.exec(text)) !== null) {
    const parts = match[1].split(",").map((p) => Number(p.trim()));
    if (parts.length < 3 || parts.some((n) => !Number.isFinite(n))) continue;
    const [x, y, z] = parts;
    minX = Math.min(minX, x);
    minY = Math.min(minY, y);
    minZ = Math.min(minZ, z);
    maxX = Math.max(maxX, x);
    maxY = Math.max(maxY, y);
    maxZ = Math.max(maxZ, z);
    count += 1;
  }
  if (count < 2) {
    throw new Error("Could not read CARTESIAN_POINT data from this STEP file.");
  }
  return {
    format: "step",
    bbox_in: {
      x: linearToInches(maxX - minX, unit),
      y: linearToInches(maxY - minY, unit),
      z: linearToInches(maxZ - minZ, unit),
    },
    part_volume_in3: null,
    volume_known: false,
    notes: [
      "STEP solid volume is not computed in the browser (needs the shop CLI / CadQuery). " +
        "The range below is a HIGH-SIDE placeholder that treats the whole AABB as chips.",
      "STEP bbox is taken from CARTESIAN_POINT entities and may include construction geometry.",
    ],
  };
}

export async function measureCadFile(file, unit) {
  const format = detectFormat(file.name);
  const buffer = await file.arrayBuffer();
  if (format === "stl") return { ...measureStlBuffer(buffer, unit), filename: file.name };
  const text = new TextDecoder("utf-8", { fatal: false }).decode(buffer);
  return { ...measureStepText(text, unit), filename: file.name };
}

export function estimateFromGeometry({
  config,
  materialName,
  geometry,
  qty = 1,
  setups = 1,
  materialSource = "shop_buys",
  turnaround = "standard",
  dueDate = null,
  asOfDate = null,
  toleranceClass = "standard",
  featureRisks = [],
  stockDimsIn = null,
}) {
  const material = findMaterial(config, materialName);
  const volumeKnown = geometry.volume_known && geometry.part_volume_in3 != null;
  const partVolume = volumeKnown ? geometry.part_volume_in3 : 0;
  const stock = stockDimsIn || geometry.bbox_in;
  const envelope = checkEnvelope(config.machine, stock);
  const reasons = envelopeReasons(config.machine, envelope);
  const cost = computeCost({
    config,
    material,
    bboxIn: geometry.bbox_in,
    partVolumeIn3: partVolume,
    overrides: {
      qty,
      setups,
      materialSource,
      turnaround,
      dueDate,
      asOfDate,
      toleranceClass,
      featureRisks,
      stockDimsIn: stockDimsIn || undefined,
    },
  });
  const status = reasons.length ? "rejected" : "ok";
  const callouts = [
    "Machining-only 3-axis mill (Tormach 1500MX). No finishes, turning, or 5-axis.",
    "Materials are pass-through at shop cost. Scrap is absorbed by the shop — not billed.",
    "This is an estimate, not a final bid. Andrew confirms from quotes@ after you proceed. A payment link arrives in that email.",
    "Catalog $/in³ and MRR_eff are TODO_REPLACE placeholders until Andrew replaces them.",
    ...(geometry.notes || []),
    ...(envelope.rotation_note ? [envelope.rotation_note] : []),
  ];
  if (stockDimsIn) {
    callouts.push("Stock dimensions overridden (AABB replaced as stock).");
    if (
      stockDimsIn.x + 1e-9 < geometry.bbox_in.x ||
      stockDimsIn.y + 1e-9 < geometry.bbox_in.y ||
      stockDimsIn.z + 1e-9 < geometry.bbox_in.z
    ) {
      callouts.push("WARNING: overridden stock is smaller than the part AABB on at least one axis.");
    }
  }
  if (cost.material_source === "customer_supplied") {
    callouts.push("Customer-supplied material: material $ is $0.");
  }
  if (cost.due_date_warning) callouts.push(cost.due_date_warning);
  if (cost.shop_review_required) {
    callouts.push("Shop review required before any customer-facing number leaves quotes@.");
  }
  return {
    status,
    geometry,
    envelope,
    cost: reasons.length || !volumeKnown ? null : cost,
    high_side_cost: reasons.length || volumeKnown ? null : cost,
    rejection_reasons: reasons,
    shop_review_required: cost.shop_review_required,
    shop_review_reasons: cost.shop_review_reasons,
    callouts,
    shop_payload: buildShopPayload({
      status,
      geometry,
      envelope,
      cost: reasons.length ? null : cost,
      high_side_cost: reasons.length || volumeKnown ? null : cost,
      rejection_reasons: reasons,
      shop_review_required: cost.shop_review_required,
      shop_review_reasons: cost.shop_review_reasons,
      stockDimsIn,
    }),
  };
}

export function buildShopPayload(result) {
  const geo = result.geometry || {};
  const bbox = geo.bbox_in || {};
  const env = result.envelope || {};
  const cost = result.cost || result.high_side_cost || {};
  const stock = result.stockDimsIn || cost.stock_in || bbox;
  return {
    estimator_status: result.status || "",
    envelope_fits: env.fits ? "yes" : "no",
    over_travel_axes: (env.over_travel_axes || []).join(","),
    bbox_x_in: bbox.x != null ? Number(bbox.x).toFixed(4) : "",
    bbox_y_in: bbox.y != null ? Number(bbox.y).toFixed(4) : "",
    bbox_z_in: bbox.z != null ? Number(bbox.z).toFixed(4) : "",
    stock_x_in: stock.x != null ? Number(stock.x).toFixed(4) : "",
    stock_y_in: stock.y != null ? Number(stock.y).toFixed(4) : "",
    stock_z_in: stock.z != null ? Number(stock.z).toFixed(4) : "",
    stock_override: result.stockDimsIn ? "yes" : "no",
    part_volume_in3: geo.volume_known ? String(geo.part_volume_in3) : "pending_step",
    cad_format: geo.format || "",
    material_key: cost.material_key || "",
    material_family: cost.material_family || "",
    material_source: cost.material_source || "",
    turnaround: cost.turnaround_applied || "",
    turnaround_requested: cost.turnaround_requested || "",
    turnaround_bumped: cost.turnaround_bumped ? "yes" : "no",
    rush_labor_mult: cost.rush_labor_mult != null ? String(cost.rush_labor_mult) : "",
    rush_setup_mult: cost.rush_setup_mult != null ? String(cost.rush_setup_mult) : "",
    setups: cost.setups != null ? String(cost.setups) : "",
    qty: cost.qty != null ? String(cost.qty) : "",
    tolerance_class: cost.tolerance_class || "",
    complexity_mult: cost.complexity_mult != null ? String(cost.complexity_mult) : "",
    feature_risks: Array.isArray(cost.feature_risks) ? cost.feature_risks.join(",") : "",
    due_date: cost.due_date || "",
    due_date_business_days:
      cost.due_date_business_days == null ? "" : String(cost.due_date_business_days),
    due_date_warning: cost.due_date_warning || "",
    shop_review_required: result.shop_review_required || cost.shop_review_required ? "yes" : "no",
    shop_review_reasons: (result.shop_review_reasons || cost.shop_review_reasons || []).join(" | "),
    catalog_values_are_placeholders: cost.catalog_values_are_placeholders ? "yes" : "no",
    quote_range_usd:
      cost.quote_low_usd != null
        ? `${Number(cost.quote_low_usd).toFixed(2)}-${Number(cost.quote_high_usd).toFixed(2)}`
        : "none",
    quote_low_usd: cost.quote_low_usd != null ? Number(cost.quote_low_usd).toFixed(2) : "",
    quote_high_usd: cost.quote_high_usd != null ? Number(cost.quote_high_usd).toFixed(2) : "",
    raw_quote_usd: cost.raw_quote_usd != null ? Number(cost.raw_quote_usd).toFixed(2) : "",
    labor_usd: cost.labor_usd != null ? Number(cost.labor_usd).toFixed(2) : "",
    material_usd: cost.material_usd != null ? Number(cost.material_usd).toFixed(2) : "",
    removal_volume_in3: cost.removal_volume_in3 != null ? String(cost.removal_volume_in3) : "",
    cut_hours: cost.cut_hours != null ? String(cost.cut_hours) : "",
    setup_hours: cost.setup_hours != null ? String(cost.setup_hours) : "",
    step_volume_pending: geo.volume_known ? "no" : "yes",
    high_side_estimate: result.high_side_cost ? "yes" : "no",
    rejection_reasons: (result.rejection_reasons || []).join(" | "),
  };
}
