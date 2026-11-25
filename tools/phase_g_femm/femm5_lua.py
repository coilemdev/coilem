"""Run the Phase G collectors' generated Lua export scripts against FEMM 5.

The Windows collectors write small Lua 4 scripts and run them inside FEMM 4.2
with `callfemm("dofile(...)")`. FEMM 5's server evaluates FEMM commands only
(no `dofile`, `openfile` or loops), accepts one client at a time and exits
when its client disconnects, so a second Lua 4 client cannot run them either.

This module recognizes the three script templates the pinned collectors
generate, exactly as generated, and performs the same queries through the
FEMM 5 Python binding, writing the same files in the same `%.17g` format:

- `tools/phase_g_femm/collect.py:export_rotor` and the 0.5.9 `tools/phase_g_loss/femm.py:export_material` (per-element corners and
  unsmoothed B for one material group),
- its outer-rotor fixed stator point query,
- `tools/femm_reference/rotor_matched_history.py:export_centroids`
  (area-weighted coil-block centroids).

Element lists, node coordinates and element B come from FEMM 5's bulk calls
(`mo_getallelements`, `mo_getallnodes`, `mo_getallb`), which return the same
values as the scripts' per-element `mo_getelement`, `mo_getnode` and
`mo_getpointvalues` (with smoothing off). Every material export re-queries a
spread of its elements with the per-element calls and refuses any difference.
Any other script is refused.
"""

from __future__ import annotations

import json
import re

STRING = r'("(?:[^"\\]|\\.)*")'
NUMBER = r"(-?[0-9][0-9.eE+-]*)"
SPOT_CHECKS = 12


def lua_string(literal):
    return json.loads(literal)  # the collectors quote paths with json.dumps


MATERIAL_BLOCK = re.compile(
    r'f=openfile' + r"\(" + STRING + r',"w"\)\n'
    r"for i=1,mo_numelements\(\) do\n"
    r"n1,n2,n3,x,y,a,g=mo_getelement\(i\)\n"
    r"if g==(\d+) then\n"
    r"x1,y1=mo_getnode\(n1\); x2,y2=mo_getnode\(n2\); x3,y3=mo_getnode\(n3\)\n"
    r"az,bx,by=mo_getpointvalues\(x,y\)\n"
    r'write\(f,format\("%\.17g,%\.17g,%\.17g,%\.17g,%\.17g,%\.17g,%\.17g,%\.17g\\n",x1,y1,x2,y2,x3,y3,bx,by\)\)\n'
    r"end end\n"
    r"closefile\(f\)"
)
QUERY_POINT = re.compile(r"az,bx,by=mo_getpointvalues\(" + NUMBER + "," + NUMBER + r"\)\n"
                         r'write\(f,format\("%\.17g,%\.17g\\n",bx,by\)\)')
CENTROID = re.compile(
    r"area=\{\}; mx=\{\}; my=\{\}\n"
    r"((?:area\[\d+\]=0; mx\[\d+\]=0; my\[\d+\]=0\n)+)"
    r"for i=1,mo_numelements\(\) do\n"
    r"n1,n2,n3,x,y,a,g=mo_getelement\(i\)\n"
    r"if area\[g\] then area\[g\]=area\[g\]\+a; mx\[g\]=mx\[g\]\+a\*x; my\[g\]=my\[g\]\+a\*y end end\n"
    r'f=openfile\(' + STRING + r',"w"\)\n'
    r'((?:write\(f,format\("%d,%\.17g,%\.17g\\n",\d+,mx\[\d+\]/area\[\d+\],my\[\d+\]/area\[\d+\]\)\)\n)+)'
    r"closefile\(f\)"
)


class Mesh:
    """Bulk element, node and element-B tables of the loaded solution."""

    def __init__(self, femm, need_b=False):
        self.femm = femm
        self.elements = femm.mo_getallelements()
        if len(self.elements) != int(femm.mo_numelements()):
            raise ValueError("FEMM 5 bulk element list is incomplete")
        self.nodes = femm.mo_getallnodes()
        self.b = femm.mo_getallb() if need_b else None
        if need_b and len(self.b) != len(self.elements):
            raise ValueError("FEMM 5 bulk element B list is incomplete")

    def node(self, index):  # mo_getelement node numbers are 1-based, as mo_getnode takes them
        return self.nodes[index - 1]


def material_export(femm, mesh, path, group):
    rows = [i for i, element in enumerate(mesh.elements) if element[6] == group]
    lines = []
    for i in rows:
        n1, n2, n3 = mesh.elements[i][:3]
        corners = [*mesh.node(n1), *mesh.node(n2), *mesh.node(n3)]
        lines.append(",".join("%.17g" % float(v) for v in (*corners, *mesh.b[i])) + "\n")
    if rows:
        step = max(1, len(rows) // (SPOT_CHECKS - 1))
        for i in sorted({rows[0], rows[-1], *rows[::step]}):
            element = femm.mo_getelement(i + 1)
            if list(element) != list(mesh.elements[i]):
                raise ValueError(f"FEMM 5 bulk element {i + 1} differs from mo_getelement")
            for n in element[:3]:
                if list(femm.mo_getnode(n)) != list(mesh.node(n)):
                    raise ValueError(f"FEMM 5 bulk node {n} differs from mo_getnode")
            values = femm.mo_getpointvalues(element[3], element[4])
            if [values[1], values[2]] != list(mesh.b[i]):
                raise ValueError(f"FEMM 5 bulk B of element {i + 1} differs from mo_getpointvalues")
    with open(path, "w", encoding="ascii", newline="") as handle:
        handle.writelines(lines)
    return {"script": "material_export", "group": group, "elements": len(rows), "spot_checks": min(len(rows), SPOT_CHECKS + 1)}


def run_script(femm, text):
    """Execute one recognized collector script; return a short record of what ran."""
    text = text.rstrip("\n")
    if text.startswith('mo_smooth("off")\n'):
        body = text[len('mo_smooth("off")\n'):]
        blocks = []
        position = 0
        while position < len(body):
            match = MATERIAL_BLOCK.match(body, position)
            if match is None:
                raise ValueError("Unrecognized Lua material-export script for FEMM 5")
            blocks.append((lua_string(match[1]), int(match[2])))
            position = match.end() + (1 if body[match.end():match.end() + 1] == "\n" else 0)
        femm.mo_smooth("off")
        mesh = Mesh(femm, need_b=True)
        return [material_export(femm, mesh, path, group) for path, group in blocks]
    match = CENTROID.fullmatch(text)
    if match is not None:
        groups = [int(g) for g in re.findall(r"area\[(\d+)\]=0", match[1])]
        written = re.findall(r'format\("%d,%\.17g,%\.17g\\n",(\d+),mx\[(\d+)\]/area\[(\d+)\],my\[(\d+)\]/area\[(\d+)\]\)', match[3])
        if any(len(set(w)) != 1 for w in written):
            raise ValueError("Unrecognized centroid write in Lua script")
        mesh = Mesh(femm)
        area = {g: 0 for g in groups}
        mx, my = dict(area), dict(area)
        for element in mesh.elements:  # same order and arithmetic as the Lua loop
            g, x, y, a = element[6], element[3], element[4], element[5]
            if g in area:
                area[g] = area[g] + a
                mx[g] = mx[g] + a * x
                my[g] = my[g] + a * y
        with open(lua_string(match[2]), "w", encoding="ascii", newline="") as handle:
            for (g, *_rest) in written:
                g = int(g)
                handle.write("%d,%.17g,%.17g\n" % (g, mx[g] / area[g], my[g] / area[g]))
        return [{"script": "centroids", "groups": len(groups)}]
    lines = text.split("\n", 1)
    opened = re.fullmatch(r'f=openfile\(' + STRING + r',"w"\)', lines[0])
    if opened is not None and len(lines) == 2 and lines[1].endswith("\nclosefile(f)"):
        body = lines[1][: -len("\nclosefile(f)")]
        points = QUERY_POINT.findall(body)
        if "\n".join(f"az,bx,by=mo_getpointvalues({x},{y})\n" + 'write(f,format("%.17g,%.17g\\n",bx,by))'
                     for x, y in points) != body:
            raise ValueError("Unrecognized Lua point-query script for FEMM 5")
        with open(lua_string(opened[1]), "w", encoding="ascii", newline="") as handle:
            for x, y in points:
                values = femm.mo_getpointvalues(float(x), float(y))
                handle.write("%.17g,%.17g\n" % (values[1], values[2]))
        return [{"script": "point_query", "points": len(points)}]
    raise ValueError("Unrecognized Lua script for FEMM 5: " + text[:120])


DOFILE = re.compile(r"dofile\(" + STRING + r"\)")


def install(femm):
    """Route the collectors' `callfemm("dofile(...)")` through run_script."""
    if getattr(femm, "_femm5_lua_scripts", None) is not None:
        return
    call = femm.callfemm
    femm._femm5_lua_scripts = []

    def callfemm(command):
        match = DOFILE.fullmatch(command.strip())
        if match is None:
            return call(command)
        path = lua_string(match[1])
        with open(path, encoding="ascii") as handle:
            record = run_script(femm, handle.read())
        femm._femm5_lua_scripts.append({"path": path, "ran": record})
        return []

    femm.callfemm = callfemm
