# Generic Field Playback v2

`coilem.field_playback.v2` is the solver-neutral visualization contract for
cached 2D field sequences. It separates the sequence description from the
storage encoding so a future binary transport can be added without changing
timeline semantics. The contract accepts legacy `layered-webp-v1` and current
`layered-raster-v1`. The shipped motor producer writes 1536 px PNG geometry,
flux-density and mesh layers, with WebP field-line layers.

The contract is suitable for rotating-machine results and tutorial scenes such
as permanent magnets, energized conductors, phase fields, and precomputed
transient induction examples. It does not prescribe how a solver produces the
frames. These tutorial/transient examples describe contract capabilities, not
shipped v2 producers. Currently only motor solves produce v2 playback, and
the public viewer uses angle timelines.

## Manifest structure

This illustrative manifest uses the current encoding with placeholder artifact
IDs. The motor producer supplies its own composition catalog and frame count.

```json
{
  "schema_version": "coilem.field_playback.v2",
  "encoding": "layered-raster-v1",
  "renderer_revision": "example-renderer-revision",
  "width_px": 1536,
  "height_px": 1536,
  "frame_count": 1,
  "timeline": {
    "kind": "angle",
    "unit": "deg_electrical",
    "loop": true,
    "direction": "increasing"
  },
  "layers": [
    {
      "id": "geometry",
      "label": "Geometry",
      "role": "geometry",
      "media_type": "image/png",
      "default_visible": true
    },
    {
      "id": "flux_density",
      "label": "Flux density",
      "role": "scalar",
      "media_type": "image/png",
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
              "media_type": "image/png",
              "byte_count": 123
            },
            "flux_density": {
              "artifact_id": "opaque-flux-id",
              "media_type": "image/png",
              "byte_count": 456
            },
            "field_lines": {
              "artifact_id": "opaque-lines-id",
              "media_type": "image/webp",
              "byte_count": 789
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
  "manifest_artifact_id": "opaque-manifest-id",
  "annotations": [],
  "numerical_snapshots": [
    {
      "artifact_id": "opaque-exact-frame-id",
      "media_type": "application/json+gzip"
    }
  ]
}
```

`renderer_revision` identifies the producer's raster implementation; the motor
cache checks it before reusing playback. `manifest_artifact_id` locates the
stored manifest. The contract also accepts optional `detail_width_px` and
`detail_height_px` together, and per-visual `detail_layers` with the same layer
IDs as `layers`. These describe a separate higher-resolution raster set when
provided; the current motor producer emits one 1536 px set and exact snapshots
rather than a separate detail set.

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

Composition IDs are also content-defined. A future permanent-magnet lesson could expose
`magnet_a`, `magnet_b`, `conductor`, and `resultant`; a two-phase lesson may
expose `phase_a`, `phase_b`, and `resultant`.

Each visual may include a compact `vector_cues` array. A cue contains a point
(`x`, `y`) in the visual's `view_box` coordinate system and a non-zero direction
(`dx`, `dy`); `magnitude` is optional. Players can use these solver-derived
vectors for static or animated direction arrows without retaining the full
numerical mesh. Producers must not infer field direction from contour traversal
order. The public motor packager samples at most a few dozen exact B-vector
cues per composition and frame. Future tutorial producers could provide the same
generic cue shape for magnets, conductors, induction examples, or other 2D
vector fields.

The v2 validator rejects undeclared compositions and layers, non-finite
coordinates, invalid or zero-length vector cues, invalid view boxes, incomplete
artifact references, and non-monotonic timelines. The frontend retains a v1
adapter so existing cached motor solves remain viewable.

Tutorial narration, quizzes, and lesson navigation belong in a separate lesson
manifest that references a field-playback manifest. Keeping those concerns
separate lets the same solved sequence appear in a tutorial, report, or design
workspace. No separate lesson-manifest producer is shipped in this checkout.
