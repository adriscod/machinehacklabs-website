import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import {
  checkEnvelope,
  computeCost,
  estimateFromGeometry,
  findMaterial,
  measureStepText,
  measureStlBuffer,
} from "./estimator.js";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const config = JSON.parse(
  readFileSync(join(root, "assets/config/quote-config.json"), "utf8")
);

test("aluminum hand-calc matches locked Python model", () => {
  const material = findMaterial(config, "aluminum");
  const cost = computeCost({
    config,
    material,
    bboxIn: { x: 4, y: 3, z: 1 },
    partVolumeIn3: 4,
  });
  assert.equal(cost.stock_volume_in3, 12);
  assert.equal(cost.removal_volume_in3, 8);
  assert.equal(cost.cut_hours, 0.6667);
  assert.equal(cost.labor_usd, 125);
  assert.equal(cost.material_usd, 4.2);
  assert.equal(cost.raw_quote_usd, 129.2);
  assert.equal(cost.quote_low_usd, 109.82);
  assert.equal(cost.quote_high_usd, 161.5);
});

test("qty scales cut and catalog material, not setup", () => {
  const material = findMaterial(config, "aluminum");
  const cost = computeCost({
    config,
    material,
    bboxIn: { x: 4, y: 3, z: 1 },
    partVolumeIn3: 4,
    overrides: { qty: 3 },
  });
  assert.equal(cost.cut_hours, 2);
  assert.equal(cost.setup_hours, 1);
  assert.equal(cost.labor_usd, 225);
  assert.equal(cost.material_usd, 12.6);
  assert.equal(cost.raw_quote_usd, 237.6);
});

test("over-travel rejects X beyond usable 19.2", () => {
  const check = checkEnvelope(config.machine, { x: 20, y: 1, z: 1 });
  assert.equal(check.fits, false);
  assert.deepEqual(check.over_travel_axes, ["x"]);
});

test("demo STL bbox and volume in inches", () => {
  const buf = readFileSync(join(root, "mhl-quote/samples/demo_block.stl"));
  const geo = measureStlBuffer(buf, "inch");
  assert.equal(geo.format, "stl");
  assert.ok(Math.abs(geo.bbox_in.x - 2) < 1e-3);
  assert.ok(Math.abs(geo.bbox_in.y - 1.5) < 1e-3);
  assert.ok(Math.abs(geo.bbox_in.z - 0.75) < 1e-3);
  assert.ok(Math.abs(geo.part_volume_in3 - 2.25) < 1e-3);
});

test("STEP CARTESIAN_POINT bbox; volume unknown", () => {
  const step = `
ISO-10303-21;
DATA;
#1=CARTESIAN_POINT('',(0.,0.,0.));
#2=CARTESIAN_POINT('',(25.4,12.7,6.35));
ENDSEC;
END-ISO-10303-21;
`;
  const geo = measureStepText(step, "mm");
  assert.equal(geo.volume_known, false);
  assert.ok(Math.abs(geo.bbox_in.x - 1) < 1e-6);
  assert.ok(Math.abs(geo.bbox_in.y - 0.5) < 1e-6);
  assert.ok(Math.abs(geo.bbox_in.z - 0.25) < 1e-6);
  const result = estimateFromGeometry({
    config,
    materialName: "steel",
    geometry: { ...geo, filename: "x.step" },
    qty: 1,
  });
  assert.equal(result.cost, null);
  assert.ok(result.high_side_cost);
  assert.equal(result.status, "ok");
});
