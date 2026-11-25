"""Independent path limits, reference mesh checks, and production wiring."""
import math

import pytest

from backend.benchmark_suite import thermal_path_audit as audit
from backend.geometry_ir import build_geometry_ir
from backend.thermal_network import (
    _square_robin_factor,
    build_network,
    end_winding_surface,
    square_bundle_resistance,
)
from tests.test_thermal_network import inputs, records


def test_registered_path_audit_passes_with_independent_references():
    result = audit.run_suite()
    assert result['status'] == 'PASS', [c for c in result['cases'] if c['status'] != 'PASS']
    assert len(result['cases']) == 26
    assert result['output_status'] == 'experimental'


@pytest.mark.parametrize('biot', [1e-9, .001, .1, 1, 10, 100, 1e9])
def test_square_series_converges_and_preserves_scaling(biot):
    coarse, fine = _square_robin_factor(biot), _square_robin_factor(biot, 512)
    assert coarse == pytest.approx(fine, rel=1e-7)
    # Equal dimensionless Bi: scaling every linear dimension by two halves R.
    r = square_bundle_resistance(.01, .04, 2, 400*biot)
    assert square_bundle_resistance(.02, .16, 2, 200*biot) == pytest.approx(r/2)
    assert r > 1/(400*biot*.04)


def test_production_axial_and_magnet_paths_have_independent_geometric_anchors():
    config, winding, losses, iron = records()
    settings = inputs()
    net = build_network(config, settings, winding, losses, iron)
    links = {(link.a,link.b):link.resistance_K_W for link in net.links}
    areas = {}
    for region in build_geometry_ir(config).regions:
        areas[region.kind] = areas.get(region.kind, 0) + region.area_mm2*1e-6
    axial = ((config.stator.stack_length_mm + winding.end_turn_length_mm)*1e-3
             / (12 * settings.conductor_k_W_mK * areas['SlotWinding'] * winding.copper_fill))
    assert links['winding','end_winding'] == pytest.approx(axial)
    length = config.stator.stack_length_mm*1e-3
    thickness = config.rotor.magnet_thickness_mm*1e-3
    assert links['magnets','rotor'] == pytest.approx(thickness**2/(3*settings.magnet_k_W_mK*areas['Magnet']*length))
    surface, side = end_winding_surface(config, winding, areas['SlotWinding'])
    assert surface*side/4 == pytest.approx(areas['SlotWinding']*winding.end_turn_length_mm*1e-3)
    assert math.isfinite(links['end_winding','end_air'])


def test_exposure_reduces_robin_coefficient_without_shrinking_bundle():
    config, winding, losses, iron = records()
    def end_path(fraction):
        return next(link.resistance_K_W for link in build_network(config, inputs(end_winding_exposed_fraction=fraction), winding, losses, iron).links
                    if (link.a,link.b)==('end_winding','end_air'))
    assert end_path(.25) > end_path(1)
