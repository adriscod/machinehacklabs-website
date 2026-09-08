from __future__ import annotations

from pathlib import Path


def write_axis_aligned_box_stl(
    path: Path,
    size_x: float,
    size_y: float,
    size_z: float,
    *,
    origin: tuple[float, float, float] = (0.0, 0.0, 0.0),
    name: str = "box",
) -> Path:
    """Write an ASCII STL rectangular box (12 triangles). Units are whatever the caller says."""
    ox, oy, oz = origin
    sx, sy, sz = size_x, size_y, size_z
    v = [
        (ox, oy, oz),
        (ox + sx, oy, oz),
        (ox + sx, oy + sy, oz),
        (ox, oy + sy, oz),
        (ox, oy, oz + sz),
        (ox + sx, oy, oz + sz),
        (ox + sx, oy + sy, oz + sz),
        (ox, oy + sy, oz + sz),
    ]
    faces: list[tuple[int, int, int]] = [
        (0, 2, 1),
        (0, 3, 2),
        (4, 5, 6),
        (4, 6, 7),
        (0, 1, 5),
        (0, 5, 4),
        (3, 6, 2),
        (3, 7, 6),
        (0, 7, 3),
        (0, 4, 7),
        (1, 2, 6),
        (1, 6, 5),
    ]
    lines = [f"solid {name}"]
    for a, b, c in faces:
        ux = v[b][0] - v[a][0]
        uy = v[b][1] - v[a][1]
        uz = v[b][2] - v[a][2]
        wx = v[c][0] - v[a][0]
        wy = v[c][1] - v[a][1]
        wz = v[c][2] - v[a][2]
        nx = uy * wz - uz * wy
        ny = uz * wx - ux * wz
        nz = ux * wy - uy * wx
        length = (nx * nx + ny * ny + nz * nz) ** 0.5 or 1.0
        nx, ny, nz = nx / length, ny / length, nz / length
        lines.append(f"  facet normal {nx:.6e} {ny:.6e} {nz:.6e}")
        lines.append("    outer loop")
        for idx in (a, b, c):
            x, y, z = v[idx]
            lines.append(f"      vertex {x:.6e} {y:.6e} {z:.6e}")
        lines.append("    endloop")
        lines.append("  endfacet")
    lines.append(f"endsolid {name}")
    path.write_text("\n".join(lines) + "\n", encoding="ascii")
    return path
