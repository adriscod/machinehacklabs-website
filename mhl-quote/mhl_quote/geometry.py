from __future__ import annotations

from pathlib import Path
from typing import assert_never

try:
    import cadquery as cq
except ImportError:  # optional extra: STEP via CadQuery/OCP
    cq = None

try:
    import numpy as np
    from stl import mesh as stl_mesh_lib
except ImportError:  # required extra: declared in requirements.txt
    np = None
    stl_mesh_lib = None

from mhl_quote.models import (
    CadFormat,
    GeometryResult,
    LengthUnit,
    Vec3,
    linear_to_inches,
    volume_to_in3,
)

STEP_SUFFIXES = {".step", ".stp"}
STL_SUFFIXES = {".stl"}


class GeometryError(ValueError):
    """STEP/STL could not be measured."""


def detect_format(path: Path) -> CadFormat:
    suffix = path.suffix.lower()
    if suffix in STEP_SUFFIXES:
        return CadFormat.STEP
    if suffix in STL_SUFFIXES:
        return CadFormat.STL
    raise GeometryError(
        f"unsupported file type {path.suffix!r}; expected .step/.stp or .stl"
    )


def measure_file(path: str | Path, unit: LengthUnit) -> GeometryResult:
    source = Path(path)
    if not source.is_file():
        raise GeometryError(f"CAD file not found: {source}")
    cad_format = detect_format(source)
    if cad_format is CadFormat.STL:
        return measure_stl(source, unit)
    if cad_format is CadFormat.STEP:
        return measure_step(source, unit)
    assert_never(cad_format)


def measure_stl(path: Path, unit: LengthUnit) -> GeometryResult:
    if np is None or stl_mesh_lib is None:
        raise GeometryError(
            "numpy-stl is required for STL files. From mhl-quote\\ run: "
            "python -m pip install -r requirements.txt"
        )

    try:
        stl_mesh = stl_mesh_lib.Mesh.from_file(str(path))
    except Exception as exc:  # noqa: BLE001 — surface loader failures as GeometryError
        raise GeometryError(f"failed to read STL {path}: {exc}") from exc

    if stl_mesh.vectors.size == 0:
        raise GeometryError(f"STL has no triangles: {path}")

    points = stl_mesh.vectors.reshape(-1, 3)
    mins = points.min(axis=0)
    maxs = points.max(axis=0)
    extents = maxs - mins
    bbox = Vec3(
        x=linear_to_inches(float(extents[0]), unit),
        y=linear_to_inches(float(extents[1]), unit),
        z=linear_to_inches(float(extents[2]), unit),
    )

    volume_native, _cog, _inertia = stl_mesh.get_mass_properties()
    part_volume = volume_to_in3(abs(float(volume_native)), unit)

    notes: list[str] = []
    # Open / non-manifold meshes produce unreliable signed volume.
    area = float(np.sum(stl_mesh.areas)) if hasattr(stl_mesh, "areas") else 0.0
    if part_volume <= 1e-9:
        notes.append(
            "STL solid volume is ~0. Mesh may be open or not watertight; "
            "removal volume will be overstated."
        )
    if area > 0 and part_volume <= 1e-9:
        notes.append("Check that the STL was exported as a closed solid.")

    return GeometryResult(
        source_path=str(path.resolve()),
        cad_format=CadFormat.STL,
        input_unit=unit,
        bbox_in=bbox,
        part_volume_in3=part_volume,
        watertight_assumed=part_volume > 1e-9,
        notes=tuple(notes),
    )


def measure_step(path: Path, unit: LengthUnit) -> GeometryResult:
    if cq is None:
        raise GeometryError(
            "CadQuery/OCP is required for STEP files. From mhl-quote\\ run: "
            "python -m pip install -r requirements-step.txt"
        )

    try:
        imported = cq.importers.importStep(str(path))
    except Exception as exc:  # noqa: BLE001
        raise GeometryError(f"failed to read STEP {path}: {exc}") from exc

    shape = imported.val() if hasattr(imported, "val") else imported
    solids = _step_solids(shape)
    if not solids:
        raise GeometryError(f"STEP file contains no solids: {path}")

    bbox = _compound_bbox_in(solids, unit)
    part_volume = 0.0
    for solid in solids:
        try:
            part_volume += volume_to_in3(abs(float(solid.Volume())), unit)
        except Exception as exc:  # noqa: BLE001
            raise GeometryError(f"could not compute STEP volume: {exc}") from exc

    notes: list[str] = []
    if len(solids) > 1:
        notes.append(f"STEP contains {len(solids)} solids; volumes were summed.")
    if unit is LengthUnit.INCH:
        notes.append(
            "STEP files are commonly stored in millimeters. "
            "If bbox looks 25.4× too large or too small, re-run with --units mm."
        )

    return GeometryResult(
        source_path=str(path.resolve()),
        cad_format=CadFormat.STEP,
        input_unit=unit,
        bbox_in=bbox,
        part_volume_in3=part_volume,
        watertight_assumed=part_volume > 1e-9,
        notes=tuple(notes),
    )


def cadquery_available() -> bool:
    return cq is not None


def _step_solids(shape: object) -> list[object]:
    if hasattr(shape, "Solids"):
        solids = list(shape.Solids())
        if solids:
            return solids
    if shape is not None:
        return [shape]
    return []


def _compound_bbox_in(solids: list[object], unit: LengthUnit) -> Vec3:
    xmin = ymin = zmin = float("inf")
    xmax = ymax = zmax = float("-inf")
    for solid in solids:
        try:
            bb = solid.BoundingBox()
        except Exception as exc:  # noqa: BLE001
            raise GeometryError(f"could not compute STEP bounding box: {exc}") from exc
        xmin = min(xmin, float(bb.xmin))
        ymin = min(ymin, float(bb.ymin))
        zmin = min(zmin, float(bb.zmin))
        xmax = max(xmax, float(bb.xmax))
        ymax = max(ymax, float(bb.ymax))
        zmax = max(zmax, float(bb.zmax))
    return Vec3(
        x=linear_to_inches(xmax - xmin, unit),
        y=linear_to_inches(ymax - ymin, unit),
        z=linear_to_inches(zmax - zmin, unit),
    )
