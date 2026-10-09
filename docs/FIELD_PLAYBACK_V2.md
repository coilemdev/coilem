# Generic Field Playback v2

`coilem.field_playback.v2` is the solver-neutral visualization contract for
cached 2D field sequences. It separates the sequence description from the
`layered-webp-v1` storage encoding so a future binary transport can be added
without changing tutorial or playback semantics.

The contract is suitable for rotating-machine results and tutorial scenes such
as permanent magnets, energized conductors, phase fields, and precomputed
transient induction examples. It does not prescribe how a solver produces the
frames.

## Manifest structure

```json
{
  "schema_version": "coilem.field_playback.v2",
  "encoding": "layered-webp-v1",
  "width_px": 768,
  "height_px": 768,
  "frame_count": 1,
  "timeline": {
    "kind": "time",
    "unit": "ms",
    "loop": true,
    "direction": "increasing"
  },
  "layers": [
    {
      "id": "geometry",
      "label": "Geometry",
      "role": "geometry",
      "media_type": "image/webp",
      "default_visible": true
    },
    {
      "id": "flux_density",
      "label": "Flux density",
      "role": "scalar",
      "media_type": "image/webp",
      "default_visible": true,
      "quantity": "magnetic_flux_density",
      "unit": "T"
    },
    {
      "id": "field_lines",
      "label": "Field lines",
      "role": "contours",
      "media_type": "image/webp",
      "default_visible": true
    }
  ],
  "compositions": [
    {"id": "magnet_a", "label": "Magnet A"},
    {"id": "conductor", "label": "Conductor"},
    {"id": "resultant", "label": "Resultant"}
  ],
  "frames": [
    {
      "index": 0,
      "coordinate": 0,
      "compositions": {
        "resultant": {
          "layers": {
            "geometry": {
              "artifact_id": "opaque-id",
              "media_type": "image/webp",
              "byte_count": 123
            }
          },
          "view_box": "-10 -10 20 20",
          "vector_cues": [
            {
              "x": 0,
              "y": 2.5,
              "dx": 1,
              "dy": 0,
              "magnitude": 0.8
            }
          ],
          "legend": {
            "label": "Flux density",
            "quantity": "magnetic_flux_density",
            "unit": "T",
            "min": 0,
            "max": 1.5
          }
        }
      }
    }
  ],
  "annotations": [],
  "numerical_snapshots": [
    {
      "artifact_id": "opaque-exact-frame-id",
      "media_type": "application/json+gzip"
    }
  ]
}
```

## Timeline

`timeline.kind` is one of:

- `angle` for mechanical or electrical rotation
- `time` for transient playback
- `phase` for an excitation phase sweep
- `step` for discrete instructional states

The unit is explicit and may be domain-specific, such as `deg_electrical`,
`deg_mechanical`, `ms`, or `index`.

`numerical_snapshots` is either empty when a producer offers raster playback
only, or contains exactly one positional snapshot for every entry in `frames`.
Partial arrays are invalid because viewers use the same index to request exact
solver geometry for a stopped frame.

## Layers and compositions

Layer IDs are chosen by the content producer. Each layer declares one semantic
role: `geometry`, `scalar`, `contours`, `vectors`, or `annotations`. This lets a
player discover how to render a layer without relying on names such as
`flux_density`.

Composition IDs are also content-defined. A permanent-magnet lesson may expose
`magnet_a`, `magnet_b`, `conductor`, and `resultant`; a two-phase lesson may
expose `phase_a`, `phase_b`, and `resultant`.

Each visual may include a compact `vector_cues` array. A cue contains a point
(`x`, `y`) in the visual's `view_box` coordinate system and a non-zero direction
(`dx`, `dy`); `magnitude` is optional. Players can use these solver-derived
vectors for static or animated direction arrows without retaining the full
numerical mesh. Producers must not infer field direction from contour traversal
order. The public motor packager samples at most a few dozen exact B-vector
cues per composition and frame, while tutorial producers can provide the same
generic cue shape for magnets, conductors, induction examples, or other 2D
vector fields.

The v2 validator rejects undeclared compositions and layers, non-finite
coordinates, invalid or zero-length vector cues, invalid view boxes, incomplete
artifact references, and non-monotonic timelines. The frontend retains a v1
adapter so existing cached motor solves remain viewable.

Tutorial narration, quizzes, and lesson navigation belong in a separate lesson
manifest that references a field-playback manifest. Keeping those concerns
separate lets the same solved sequence appear in a tutorial, report, or design
workspace.
