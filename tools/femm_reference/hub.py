"""Preserved 0.5 mm hub bulk recipe and its preprocessing audit."""

from __future__ import annotations

import math

from tools.femm_reference import phase_f, runtime


def load_base():
    return phase_f


def identity(base, bulk_mesh_mm, *, field_run):
    return {"base_identity": runtime.identity("f"), "bulk_mesh_mm": bulk_mesh_mm, "mesh_recipe": recipe(bulk_mesh_mm)}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def recipe(bulk_mesh_mm):
    return {
        "name": "hub-explicit-bulk-mesh-variant-v1",
        "bulk_mesh_mm": bulk_mesh_mm,
        "base_bulk_mesh_mm": 0.25,
        "overridden_materials": ["Steel_stator", "Steel_rotor", "Copper"],
        "magnet_and_pocket_mesh_size_mm": 0.15,
        "airgap_mesh_size_mm": 0.125,
        "max_arc_segment_deg": 0.1418212364185206,
        "precision": 1e-8,
        "min_angle_deg": 30,
        "all_other_preprocessing_and_extraction": "Unchanged sealed base-library calls",
        "mixed_field_origin_exception_pending_owner_review": True,
    }


class BulkMeshProxy:
    """Change only the explicit mesh-size argument for iron and copper blocks."""

    def __init__(self, femm, bulk_mesh_mm):
        self.femm, self.bulk_mesh_mm, self.audit = femm, bulk_mesh_mm, []

    def __getattr__(self, name):
        return getattr(self.femm, name)

    def mi_setblockprop(self, *args):
        require(len(args) == 7, "Unexpected FEMM block-property signature")
        material, automesh, old_mesh, circuit, direction, group, turns = args
        override = material.startswith("Steel_") or material == "Copper"
        require(not override or old_mesh == 0.25, "Original bulk mesh recipe changed")
        new_mesh = self.bulk_mesh_mm if override else old_mesh
        effective = (material, automesh, new_mesh, circuit, direction, group, turns)
        require(all(args[i] == effective[i] for i in (0, 1, 3, 4, 5, 6)), "A non-mesh parameter changed")
        self.audit.append(
            {
                "material": material,
                "original_mesh_mm": old_mesh,
                "effective_mesh_mm": new_mesh,
                "overridden": override,
                "circuit": circuit,
                "group": group,
                "signed_turns": turns,
            }
        )
        return self.femm.mi_setblockprop(*effective)


def lower(base, femm, runtime, config, ir, currents, steel, bulk_mesh_mm):
    proxy = BulkMeshProxy(femm, bulk_mesh_mm)
    settings = base.lower_model(proxy, runtime, config, ir, currents, steel)
    require(
        settings["airgap_mesh_size_mm"] == 0.125
        and math.isclose(settings["max_arc_segment_deg"], recipe(bulk_mesh_mm)["max_arc_segment_deg"], rel_tol=0, abs_tol=1e-14),
        "Hub gap mesh or arc cap changed",
    )
    require(sum(row["overridden"] for row in proxy.audit) == 83, "Unexpected hub bulk-region count")
    require(
        all(row["original_mesh_mm"] == row["effective_mesh_mm"] for row in proxy.audit if not row["overridden"]),
        "Gap, magnet, pocket or no-mesh label was changed",
    )
    settings.update(
        other_mesh_size_mm=bulk_mesh_mm,
        base_other_mesh_size_mm=0.25,
        block_property_override_audit=proxy.audit,
        mesh_variant_recipe=recipe(bulk_mesh_mm),
    )
    return settings


def preflight(base, runtime, config, steel, bulk_mesh_mm):
    checked = base.preflight(runtime, config, steel, "production")
    checks = []
    for index, theta in enumerate(base.GRID):
        ir, _ = base.rotated_ir(runtime, config, theta)
        currents = base.driver_vector(runtime, config, theta, "production")
        fake = base.FakeFEMM()
        settings = lower(base, fake, runtime, config, ir, currents, steel, bulk_mesh_mm)
        checked["all_48_rotated_ir_checks"][index].update(other_mesh_size_mm=bulk_mesh_mm, base_other_mesh_size_mm=0.25)
        checks.append(
            {
                "electrical_angle_deg": theta,
                "status": "PASS",
                "calls": len(fake.calls),
                "bulk_overrides": sum(row["overridden"] for row in settings["block_property_override_audit"]),
            }
        )
    checked.update(variant_fake_lowering=checks, mesh_recipe=recipe(bulk_mesh_mm), field_solves_started=False, native_phase_f_results_read=False)
    return checked
