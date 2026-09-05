from __future__ import annotations

from pathlib import Path

import pytest

from mhl_quote.geometry import cadquery_available, detect_format, measure_file, measure_stl
from mhl_quote.models import CadFormat, LengthUnit
from tests.stl_box import write_axis_aligned_box_stl


def test_detect_format() -> None:
    assert detect_format(Path("part.STEP")) is CadFormat.STEP
    assert detect_format(Path("part.stp")) is CadFormat.STEP
    assert detect_format(Path("part.stl")) is CadFormat.STL
    with pytest.raises(ValueError):
        detect_format(Path("part.ipt"))


def test_stl_bbox_and_volume_inches(tmp_path: Path) -> None:
    stl = write_axis_aligned_box_stl(tmp_path / "block.stl", 2.0, 3.0, 1.0)
    geo = measure_stl(stl, LengthUnit.INCH)
    assert geo.cad_format is CadFormat.STL
    assert geo.bbox_in.x == pytest.approx(2.0, abs=1e-4)
    assert geo.bbox_in.y == pytest.approx(3.0, abs=1e-4)
    assert geo.bbox_in.z == pytest.approx(1.0, abs=1e-4)
    assert geo.part_volume_in3 == pytest.approx(6.0, abs=1e-3)
    assert geo.watertight_assumed is True


def test_stl_mm_converts_to_inches(tmp_path: Path) -> None:
    # 25.4 × 25.4 × 25.4 mm = 1 in cube
    stl = write_axis_aligned_box_stl(tmp_path / "mm_cube.stl", 25.4, 25.4, 25.4)
    geo = measure_file(stl, LengthUnit.MM)
    assert geo.bbox_in.x == pytest.approx(1.0, abs=1e-4)
    assert geo.part_volume_in3 == pytest.approx(1.0, abs=1e-3)


@pytest.mark.skipif(not cadquery_available(), reason="CadQuery/OCP not installed")
def test_step_bbox_and_volume(tmp_path: Path) -> None:
    import cadquery as cq

    step_path = tmp_path / "block.step"
    # CadQuery box() is centered; size is full extents. Units are mm.
    cq.Workplane("XY").box(50.8, 25.4, 12.7).val().exportStep(str(step_path))
    geo = measure_file(step_path, LengthUnit.MM)
    assert geo.cad_format is CadFormat.STEP
    assert geo.bbox_in.x == pytest.approx(2.0, abs=1e-3)
    assert geo.bbox_in.y == pytest.approx(1.0, abs=1e-3)
    assert geo.bbox_in.z == pytest.approx(0.5, abs=1e-3)
    assert geo.part_volume_in3 == pytest.approx(1.0, abs=1e-3)
