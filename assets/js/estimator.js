/**
 * Browser/Node port of the MHL-CF-001 cost model + STL/STEP geometry.
 * Keep rounding and formulas aligned with mhl-quote/mhl_quote/cost.py.
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

export function findMaterial(config, name) {
  const needle = String(name).trim().toLowerCase();
  const materials = config.materials || {};
  if (materials[needle]) return { key: needle, ...materials[needle] };
  for (const [key, spec] of Object.entries(materials)) {
    const aliases = (spec.aliases || []).map((a) => String(a).toLowerCase());
    if (needle === String(spec.family || "").toLowerCase() || aliases.includes(needle)) {
      return { key, ...spec };
    }
  }
  throw new Error(`unknown material ${name}`);
}

export function computeCost({ config, material, bboxIn, partVolumeIn3, overrides = {} }) {
  const qty = overrides.qty == null ? 1 : Number(overrides.qty);
  if (qty < 1 || !Number.isFinite(qty)) throw new Error("qty must be >= 1");

  const stock = overrides.stockDimsIn || bboxIn;
  const stockVol = Math.max(0, vecVolume(stock));
  const partVol = Math.max(0, Number(partVolumeIn3) || 0);
  const removalVol = Math.max(0, stockVol - partVol);

  const mrr = overrides.mrrEffIn3PerHr == null ? material.mrr_eff_in3_per_hr : overrides.mrrEffIn3PerHr;
  if (mrr <= 0) throw new Error("MRR_eff must be > 0");

  const setup = overrides.setupHours == null ? config.shop.setup_hours : overrides.setupHours;
  if (setup < 0) throw new Error("setup_hours must be >= 0");

  const cutEach = removalVol === 0 ? 0 : removalVol / mrr;
  const cut = cutEach * qty;
  const labor = (setup + cut) * config.shop.rate_usd_per_hr;

  let materialUsd;
  let catalogEstimate;
  if (overrides.stockPurchaseCostUsd != null) {
    materialUsd = Number(overrides.stockPurchaseCostUsd);
    catalogEstimate = false;
  } else {
    materialUsd = stockVol * material.cost_usd_per_in3 * qty;
    catalogEstimate = true;
  }

  const raw = money(Math.max(materialUsd + labor, config.shop.min_charge_usd));
  return {
    material_key: material.key,
    material_label: material.label,
    qty,
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
    raw_quote_usd: raw,
    quote_low_usd: money(raw * config.shop.band_low),
    quote_high_usd: money(raw * config.shop.band_high),
    min_charge_applied: materialUsd + labor < config.shop.min_charge_usd,
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

export function estimateFromGeometry({ config, materialName, geometry, qty = 1 }) {
  const material = findMaterial(config, materialName);
  const volumeKnown = geometry.volume_known && geometry.part_volume_in3 != null;
  const partVolume = volumeKnown ? geometry.part_volume_in3 : 0;
  const envelope = checkEnvelope(config.machine, geometry.bbox_in);
  const reasons = envelopeReasons(config.machine, envelope);
  const cost = computeCost({
    config,
    material,
    bboxIn: geometry.bbox_in,
    partVolumeIn3: partVolume,
    overrides: { qty },
  });
    const status = reasons.length ? "rejected" : "ok";
  return {
    status,
    geometry,
    envelope,
    cost: reasons.length || !volumeKnown ? null : cost,
    high_side_cost: reasons.length || volumeKnown ? null : cost,
    rejection_reasons: reasons,
    callouts: [
      "Machining-only 3-axis mill (Tormach 1500MX). No finishes, turning, or 5-axis.",
      "Materials are pass-through at shop cost. Scrap is absorbed by the shop — not billed.",
      "This is a range, not a single-dollar quote. Andrew reviews before any customer reply.",
      ...(geometry.notes || []),
      ...(envelope.rotation_note ? [envelope.rotation_note] : []),
    ],
  };
}
