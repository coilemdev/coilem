"""FEMM lowering of PR100's exact shared winding/geometry IR.

No native solver is imported. Whole-slot flux sampling remains the pinned
adapter's method. Split slots use the area/volume average of A_z in each actual
FEMM block, matching the region-specific reduction of PR100.
FEMM integral definitions: https://www.femm.info/doku/lib/exe/fetch.php?media=upload%3Afiles%3Amanual.pdf
"""
from __future__ import annotations

import math


def regions(config, geom):
    from backend.geometry_ir import build_geometry_ir
    ir = build_geometry_ir(config, geom=geom)
    assert not ir.validation_report().issues, ir.validation_report().issues
    return ir


def draw_stator_regions(femm, config, geom, maxseg):
    """Draw the shared slot/tooth boundaries once, preserving every T junction."""
    unique = {}
    points = {}
    for region in regions(config, geom).regions:
        if region.kind not in ("StatorTooth", "SlotWinding"):
            continue
        for loop in region.loops:
            for seg in loop.segments:
                a = (seg.start.x_mm, seg.start.y_mm)
                b = (seg.end.x_mm, seg.end.y_mm)
                ra, rb = tuple(round(v, 10) for v in a), tuple(round(v, 10) for v in b)
                if ra == rb:
                    continue
                center = None if seg.center is None else (round(seg.center.x_mm, 10), round(seg.center.y_mm, 10))
                key = (seg.kind, tuple(sorted((ra, rb))), center)
                unique.setdefault(key, seg)
                points.setdefault(ra, a)
                points.setdefault(rb, b)
    # Register all junctions before adding edges; FEMM splits intersected arcs.
    for x,y in points.values():
        femm.mi_addnode(x,y)
    for seg in unique.values():
        a,b = (seg.start.x_mm,seg.start.y_mm),(seg.end.x_mm,seg.end.y_mm)
        if seg.kind == 'line':
            femm.mi_drawline(*a,*b)
        else:
            assert seg.sweep_deg is not None
            if seg.sweep_deg >= 0:
                femm.mi_drawarc(*a,*b,seg.sweep_deg,maxseg)
            else:
                femm.mi_drawarc(*b,*a,-seg.sweep_deg,maxseg)


def polygon(loop):
    points=[]
    for seg in loop.segments:
        a=(seg.start.x_mm,seg.start.y_mm)
        points.append(a)
        if seg.kind=='arc':
            assert seg.center is not None and seg.sweep_deg is not None
            c=(seg.center.x_mm,seg.center.y_mm)
            radius=math.hypot(a[0]-c[0],a[1]-c[1])
            angle=math.atan2(a[1]-c[1],a[0]-c[0])
            count=max(1,math.ceil(abs(seg.sweep_deg)/0.25))
            for i in range(1,count):
                theta=angle+math.radians(seg.sweep_deg)*i/count
                points.append((c[0]+radius*math.cos(theta),c[1]+radius*math.sin(theta)))
    return points


def inside(point, poly):
    x,y=point; hit=False
    for (x1,y1),(x2,y2) in zip(poly,poly[1:]+poly[:1]):
        if (y1>y)!=(y2>y) and x<(x2-x1)*(y-y1)/(y2-y1)+x1:
            hit=not hit
    return hit


def label_point(region):
    poly=polygon(region.loops[0])
    cross=[a[0]*b[1]-b[0]*a[1] for a,b in zip(poly,poly[1:]+poly[:1])]
    area=sum(cross)
    assert abs(area)>1e-12
    center=(sum((a[0]+b[0])*v for a,b,v in zip(poly,poly[1:]+poly[:1],cross))/(3*area),
            sum((a[1]+b[1])*v for a,b,v in zip(poly,poly[1:]+poly[:1],cross))/(3*area))
    if inside(center,poly):
        return center
    # Deterministic fallback for nonconvex shoe regions; never put a label on an edge.
    xs,ys=zip(*poly)
    for iy in range(1,31):
        for ix in range(1,31):
            point=(min(xs)+(max(xs)-min(xs))*ix/31,min(ys)+(max(ys)-min(ys))*iy/31)
            if inside(point,poly):
                return point
    raise ValueError('No interior block label: '+region.region_id)


def winding_regions(config,geom):
    return [r for r in regions(config,geom).regions if r.kind=='SlotWinding']


def assignment(region):
    # winding:phase:direction:slotN[:layerN]
    parts=region.source_group.split(':')
    assert parts[0]=='winding' and parts[1] in 'ABC' and parts[2] in ('in','out')
    slot=int(parts[3].removeprefix('slot'))
    layer=int(parts[4].removeprefix('layer')) if len(parts)>4 else 1
    return slot,layer,parts[1],parts[2]


def apply_current(self,femm,config,geom,elec_angle_deg):
    from backend.geometry_drawer import compute_3phase_current_density_for_rotor_elec
    currents=compute_3phase_current_density_for_rotor_elec(config,elec_angle_deg)
    for region in winding_regions(config,geom):
        slot,layer,phase,direction=assignment(region)
        density=currents[phase] * (1 if direction=='in' else -1)
        name=f'Coil_v3_s{slot}_l{layer}'
        femm.mi_addmaterial(name,1,1,0,density,0,0,0,1,0,0,0,0,0)
        femm.mi_addblocklabel(*label_point(region))
        femm.mi_selectlabel(*label_point(region))
        self._set_femm_blockprop(femm,name,config,geom,'slot')
        femm.mi_clearselected()


def split_flux_contributions(self,femm,config,geom):
    from backend.geometry_ir import slot_layer_split, slot_layer_assignments
    from backend.winding_utils import flux_linkage_slot_side_turn_factor
    if slot_layer_split(config) is None:
        return self._v3_original_flux_contributions(femm,config,geom)
    factor=flux_linkage_slot_side_turn_factor(config.winding.type,config.winding.layers,config.winding.parallel_paths)
    stack=config.stator.stack_length_mm*1e-3
    rows=[]
    for region in winding_regions(config,geom):
        slot,layer,phase,direction=assignment(region)
        side=next(s for s in slot_layer_assignments(config,slot) if s.layer==layer)
        femm.mo_clearblock();femm.mo_selectblock(*label_point(region))
        volume=float(femm.mo_blockintegral(10))
        area=float(femm.mo_blockintegral(5))
        integral=float(femm.mo_blockintegral(1))
        femm.mo_clearblock()
        assert volume>0 and math.isfinite(integral)
        # Detect mislabelled/merged regions before accepting any linkage.
        assert abs(area*1e6-region.area_mm2)<=max(1e-5,region.area_mm2*0.005), (region.region_id,area*1e6,region.area_mm2)
        rows.append({'slot_index':slot,'layer':layer,'phase':phase,'direction':direction,
                     'turn_fraction':side.turn_fraction,'center_angle_deg':math.degrees(geom.slots[slot].center_angle_rad),
                     'sample_count':None,'az_avg_wb_per_m':integral/volume,'slot_area_m2':area,
                     'flux_extraction_method':'FEMM block integral A / block volume',
                     '_sign':1 if direction=='in' else -1})
    reference=sum(r['az_avg_wb_per_m']*r['slot_area_m2'] for r in rows)/sum(r['slot_area_m2'] for r in rows)
    for r in rows:
        r['az_reference_wb_per_m']=reference
        r['az_effective_wb_per_m']=r['az_avg_wb_per_m']-reference
        r['flux_linkage_contribution_wb']=r.pop('_sign')*r['turn_fraction']*factor*config.winding.turns_per_coil*stack*r['az_effective_wb_per_m']
    return rows


def slot_excitation_contributions(self,femm,config,geom,elec_angle_deg):
    """Read actual J*dA from each physical winding region, with hard guards."""
    from backend.excitation import resolve_phase_current_sample
    from backend.geometry_drawer import compute_3phase_current_density_for_rotor_elec
    from backend.geometry_ir import slot_layer_assignments
    sample=resolve_phase_current_sample(config,elec_angle_deg)
    currents=dict(zip('ABC',sample.phase_current_a))
    densities=compute_3phase_current_density_for_rotor_elec(config,elec_angle_deg)
    rows=[]
    for region in winding_regions(config,geom):
        slot,layer,phase,direction=assignment(region)
        side=next(s for s in slot_layer_assignments(config,slot) if s.layer==layer)
        sign=1 if direction=='in' else -1
        femm.mo_clearblock();femm.mo_selectblock(*label_point(region))
        amp_turns=float(femm.mo_blockintegral(7))
        area=float(femm.mo_blockintegral(5))
        femm.mo_clearblock()
        assert area>0 and math.isfinite(amp_turns)
        assert abs(area*1e6-region.area_mm2)<=max(1e-5,region.area_mm2*0.005), (region.region_id,area*1e6,region.area_mm2)
        expected=sign*densities[phase]*area*1e6
        assert abs(amp_turns-expected)<=max(1e-6,abs(expected)*1e-6), ('FEMM source mismatch',region.region_id,amp_turns,expected)
        rows.append({'slot_index_modeled':slot,'slot_index_global':slot,
                     'phase':phase,'direction':direction,'layer':layer,
                     'turn_fraction':side.turn_fraction,'center_angle_mech_deg':math.degrees(geom.slots[slot].center_angle_rad),
                     'slot_area_m2':area,'effective_current_density_a_per_m2':amp_turns/area,
                     'integrated_amp_turns_a':amp_turns,'slot_current_a':amp_turns/config.winding.turns_per_coil,
                     'phase_current_a':sign*currents[phase], 'turns_per_coil':config.winding.turns_per_coil})
    return rows


def current_metadata(self,config,elec_angle_deg):
    from backend.excitation import resolve_phase_current_sample
    from backend.geometry_drawer import current_angle_elec_deg_for_rotor_elec
    sample=resolve_phase_current_sample(config,elec_angle_deg)
    return current_angle_elec_deg_for_rotor_elec(config,elec_angle_deg),list(sample.phase_current_a)


def audited_flux(self,femm,config,geom):
    try:
        rows=split_flux_contributions(self,femm,config,geom)
        expected=len(winding_regions(config,geom))
        assert len(rows)==expected,('Missing no-load winding extraction',len(rows),expected)
        evidence=getattr(self,'_v3_flux_evidence',[])
        evidence.append({'rotor_offset_rad':getattr(self,'_last_rotor_offset_rad',None),'rows':rows})
        self._v3_flux_evidence=evidence
        return rows
    except Exception as exc:
        failures=getattr(self,'_v3_extraction_failures',[])
        failures.append({'kind':'flux','error':repr(exc)})
        self._v3_extraction_failures=failures
        raise


def audited_source(self,femm,config,geom,elec_angle_deg):
    try:
        rows=slot_excitation_contributions(self,femm,config,geom,elec_angle_deg)
        evidence=getattr(self,'_v3_source_evidence',[])
        evidence.append({'electrical_angle_deg':elec_angle_deg,'rows':rows})
        self._v3_source_evidence=evidence
        return rows
    except Exception as exc:
        failures=getattr(self,'_v3_extraction_failures',[])
        failures.append({'kind':'source','angle_deg':elec_angle_deg,'error':repr(exc)})
        self._v3_extraction_failures=failures
        raise


def install():
    import backend.geometry_drawer as geometry_drawer
    from path_compat import get_wine_compatible_path,get_native_path_from_wine_path
    geometry_drawer.get_wine_compatible_path=get_wine_compatible_path
    geometry_drawer.get_native_path_from_wine_path=get_native_path_from_wine_path
    from backend.femm_geometry import FEMMGeometryMixin
    from backend.femm_extraction import FEMMExtractionMixin
    from backend.geometry_ir import slot_layer_assignments
    if getattr(FEMMExtractionMixin,'_v3_installed',False):
        return
    FEMMGeometryMixin._apply_winding_current=apply_current
    FEMMExtractionMixin._slot_extraction_assignments=staticmethod(lambda config,slot:slot_layer_assignments(config,slot.slot_index))
    FEMMExtractionMixin._v3_original_flux_contributions=FEMMExtractionMixin._extract_flux_linkage_slot_contributions
    FEMMExtractionMixin._extract_flux_linkage_slot_contributions=audited_flux
    FEMMExtractionMixin._extract_slot_excitation_contributions=audited_source
    FEMMExtractionMixin._slot_excitation_current_metadata=current_metadata
    FEMMExtractionMixin._v3_installed=True
