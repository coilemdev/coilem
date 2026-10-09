use std::env;

use crate::motor::MotorConfig;

pub const DEFAULT_FIXTURE: &str = "schemas/v1/examples/spm_4p12s_drone.json";

#[derive(Debug, Clone, PartialEq)]
pub struct CliOptions {
    pub show_help: bool,
    pub help_topic: HelpTopic,
    pub sweep_mode: bool,
    pub serial: bool,
    pub workers: Option<usize>,
    pub n_positions: usize,
    pub sweep_span_deg: Option<f64>,
    pub rotor_angle_deg: f64,
    pub input_path: String,
    pub mesh_input_path: Option<String>,
    pub batch_input_path: Option<String>,
    pub output_path: Option<String>,
    pub field_diagnostics: bool,
    pub assert_symmetry: bool,
    /// Solve physics mode. Default magnetostatic; `thermal` requires
    /// COILEM_THERMAL_ENABLED=1.
    pub solve_mode: SolveMode,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SolveMode {
    Magnetostatic,
    Field,
    Teaching,
    Thermal,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HelpTopic {
    Overview,
    Modes,
    Single,
    Sweep,
    Batch,
    Field,
    Teaching,
    Thermal,
}

impl HelpTopic {
    fn parse(raw: Option<&str>) -> Result<Self, String> {
        match raw.map(|value| value.trim().to_ascii_lowercase()) {
            None => Ok(Self::Overview),
            Some(value) => match value.as_str() {
                "" | "overview" | "-h" | "--help" => Ok(Self::Overview),
                "mode" | "modes" => Ok(Self::Modes),
                "single" | "solve" | "magnetostatic" => Ok(Self::Single),
                "sweep" => Ok(Self::Sweep),
                "batch" => Ok(Self::Batch),
                "field" | "generic" => Ok(Self::Field),
                "teaching" | "tutorial" => Ok(Self::Teaching),
                "thermal" | "heat" => Ok(Self::Thermal),
                other => Err(format!(
                    "unknown help topic '{other}' \
                     (expected modes|single|sweep|batch|field|teaching|thermal)"
                )),
            },
        }
    }

    fn for_mode(mode: SolveMode) -> Self {
        match mode {
            SolveMode::Magnetostatic => Self::Single,
            SolveMode::Field => Self::Field,
            SolveMode::Teaching => Self::Teaching,
            SolveMode::Thermal => Self::Thermal,
        }
    }
}

impl SolveMode {
    pub fn parse(raw: &str) -> Result<Self, String> {
        match raw.trim().to_ascii_lowercase().as_str() {
            "magnetostatic" | "emag" | "magnetic" => Ok(Self::Magnetostatic),
            "field" | "generic" => Ok(Self::Field),
            "teaching" | "tutorial" => Ok(Self::Teaching),
            "thermal" | "heat" | "heat_flow" => Ok(Self::Thermal),
            other => Err(format!(
                "unknown --mode '{other}' (expected magnetostatic|field|teaching|thermal)"
            )),
        }
    }
}

pub fn thermal_mode_enabled_from_env() -> bool {
    truthy_env_value(env::var("COILEM_THERMAL_ENABLED").ok().as_deref())
}

#[derive(Debug, Clone, Default)]
struct CliEnvironment {
    workers: Option<String>,
    field_diagnostics_openem: Option<String>,
    field_diagnostics_legacy: Option<String>,
    assert_symmetry: Option<String>,
}

impl CliEnvironment {
    fn capture() -> Self {
        Self {
            workers: env::var("COILEM_MAGNETO2D_WORKERS").ok(),
            field_diagnostics_openem: env::var("COILEM_MAGNETO2D_FIELD_DIAGNOSTICS").ok(),
            field_diagnostics_legacy: env::var("MAGNETO2D_FIELD_DIAGNOSTICS").ok(),
            assert_symmetry: env::var("MAGNETO2D_ASSERT_SYMMETRY").ok(),
        }
    }
}

impl CliOptions {
    pub fn from_process_args<I>(args: I) -> Result<Self, String>
    where
        I: IntoIterator<Item = String>,
    {
        Self::from_args_and_env(args, CliEnvironment::capture())
    }

    fn from_args_and_env<I, S>(args: I, runtime_env: CliEnvironment) -> Result<Self, String>
    where
        I: IntoIterator<Item = S>,
        S: Into<String>,
    {
        let args: Vec<String> = args.into_iter().map(Into::into).collect();

        let mut options = Self {
            show_help: false,
            help_topic: HelpTopic::Overview,
            sweep_mode: false,
            serial: false,
            workers: runtime_env
                .workers
                .as_deref()
                .and_then(|raw| raw.trim().parse::<usize>().ok())
                .filter(|&n| n >= 1),
            n_positions: 18,
            sweep_span_deg: None,
            rotor_angle_deg: 0.0,
            input_path: DEFAULT_FIXTURE.to_string(),
            mesh_input_path: None,
            batch_input_path: None,
            output_path: None,
            field_diagnostics: truthy_env_value(runtime_env.field_diagnostics_openem.as_deref())
                || truthy_env_value(runtime_env.field_diagnostics_legacy.as_deref()),
            assert_symmetry: truthy_env_value(runtime_env.assert_symmetry.as_deref()),
            solve_mode: SolveMode::Magnetostatic,
        };

        if args.first().map(String::as_str) == Some("help") {
            if args.len() > 2 {
                return Err("help accepts at most one topic \
                     (modes|single|sweep|batch|teaching|thermal)"
                    .to_string());
            }
            options.show_help = true;
            options.help_topic = HelpTopic::parse(args.get(1).map(String::as_str))?;
            return Ok(options);
        }

        let mut i = 0;
        while i < args.len() {
            match args[i].as_str() {
                "-h" | "--help" => {
                    options.show_help = true;
                }
                "--mode" => {
                    if i + 1 < args.len() {
                        if matches!(args[i + 1].as_str(), "-h" | "--help" | "help") {
                            options.show_help = true;
                            options.help_topic = HelpTopic::Modes;
                        } else {
                            options.solve_mode = SolveMode::parse(&args[i + 1])?;
                            options.help_topic = HelpTopic::for_mode(options.solve_mode);
                        }
                        i += 1;
                    } else {
                        return Err(
                            "--mode requires magnetostatic|field|teaching|thermal".to_string()
                        );
                    }
                }
                "--sweep" => {
                    options.sweep_mode = true;
                    options.help_topic = HelpTopic::Sweep;
                    if i + 1 < args.len() && args[i + 1].parse::<usize>().is_ok() {
                        options.n_positions = args[i + 1].parse().unwrap();
                        i += 1;
                    }
                }
                "--mesh-only" => {
                    return Err(
                        "--mesh-only was removed from the Magneto2D Rust CLI; use the backend Gmsh mesh preview path".to_string(),
                    );
                }
                "--sweep-span-deg" => {
                    if i + 1 < args.len() {
                        options.sweep_span_deg = Some(
                            args[i + 1]
                                .parse()
                                .map_err(|e| format!("invalid --sweep-span-deg: {e}"))?,
                        );
                        i += 1;
                    }
                }
                "--serial" => {
                    options.serial = true;
                }
                "--workers" => {
                    if i + 1 < args.len() {
                        let raw = &args[i + 1];
                        let n: usize = raw
                            .parse()
                            .map_err(|e| format!("invalid --workers value '{raw}': {e}"))?;
                        if n >= 1 {
                            options.workers = Some(n);
                        }
                        i += 1;
                    }
                }
                "--field-diagnostics" => {
                    options.field_diagnostics = true;
                }
                "--rotor-angle-deg" => {
                    options.help_topic = HelpTopic::Single;
                    if i + 1 < args.len() {
                        options.rotor_angle_deg = args[i + 1]
                            .parse()
                            .map_err(|e| format!("invalid --rotor-angle-deg: {e}"))?;
                        i += 1;
                    }
                }
                "--mesh-input" => {
                    options.help_topic = HelpTopic::Single;
                    if i + 1 < args.len() {
                        options.mesh_input_path = Some(args[i + 1].clone());
                        i += 1;
                    }
                }
                "--batch-input" => {
                    options.help_topic = HelpTopic::Batch;
                    if i + 1 < args.len() {
                        options.batch_input_path = Some(args[i + 1].clone());
                        i += 1;
                    }
                }
                "--mesher" => {
                    let value = args
                        .get(i + 1)
                        .cloned()
                        .unwrap_or_else(|| "<missing>".to_string());
                    return Err(format!(
                        "--mesher was removed from the Magneto2D Rust CLI; generate a Gmsh solve mesh artifact upstream instead (got {value})"
                    ));
                }
                "--assert-symmetry" => {
                    options.assert_symmetry = true;
                }
                "-o" => {
                    if i + 1 < args.len() {
                        options.output_path = Some(args[i + 1].clone());
                        i += 1;
                    }
                }
                other if !other.starts_with('-') => {
                    options.input_path = other.to_string();
                }
                _ => {}
            }
            i += 1;
        }

        Ok(options)
    }

    pub fn effective_workers(&self) -> Option<usize> {
        self.workers
            .or_else(|| if self.serial { Some(1) } else { None })
    }

    pub fn rotor_angle_rad(&self) -> f64 {
        self.rotor_angle_deg.to_radians()
    }

    pub fn apply_process_flags(&self) {
        if self.assert_symmetry {
            env::set_var("MAGNETO2D_ASSERT_SYMMETRY", "1");
            eprintln!("magneto2d: assert_symmetry=on (integrator per-quadrant hard-assertions)");
        }
        if self.field_diagnostics {
            env::set_var("COILEM_MAGNETO2D_FIELD_DIAGNOSTICS", "1");
            eprintln!("magneto2d: field_diagnostics=on (A_z/B_r airgap spectra)");
        }
    }
}

pub fn help_text(topic: HelpTopic) -> &'static str {
    match topic {
        HelpTopic::Overview => {
            r#"Usage:
  magneto2d [fixture.json] [options]
  magneto2d help [TOPIC]

Runs a single-angle magnetostatic solve by default. If no fixture is supplied,
uses schemas/v1/examples/spm_4p12s_drone.json.

Help topics:
  modes                      Valid values accepted by --mode
  single                     Single-angle magnetostatic solve
  sweep                      Fixed-mesh rotor sweep
  batch                      Imported per-angle mesh batch
  field                      Generic solve-ready 2D field problem
  teaching                   Self-contained teaching field solve
  thermal                    Feature-gated thermal solve

Examples:
  magneto2d help modes
  magneto2d help sweep
  magneto2d --mode teaching --help

Options:
  -h, --help                 Show this help text and exit without solving
  --mode MODE                Physics mode: magnetostatic (default), field, teaching, or thermal
                             (requires COILEM_THERMAL_ENABLED=1)
  --sweep [N]                Run a rotor sweep with N positions (default: 18)
  --sweep-span-deg DEG       Sweep span in electrical degrees (default: 360)
  --serial                   Force a one-thread sweep
  --workers N                Use N rayon worker threads for sweep positions
  --rotor-angle-deg DEG      Single-solve rotor angle in mechanical degrees
  --mesh-input PATH          Reuse a solve mesh artifact JSON
  --batch-input PATH         Run imported-mesh jobs from a batch JSON
  --field-diagnostics        Emit high-volume airgap field diagnostics
  --assert-symmetry          Enable per-quadrant symmetry assertions
  -o PATH                    Write JSON report to PATH instead of stdout

Environment:
  COILEM_MAGNETO2D_WORKERS   Default worker count when --workers is omitted
  COILEM_THERMAL_ENABLED     Gate for --mode thermal (off by default)
"#
        }
        HelpTopic::Modes => {
            r#"Usage: magneto2d [fixture.json] --mode MODE [options]

Valid MODE values:
  magnetostatic              Motor field solve (default)
                             aliases: emag, magnetic
  field                      Generic solve-ready 2D magnetostatic field problem
                             alias: generic
  teaching                   Self-contained teaching field solve
                             alias: tutorial
  thermal                    Feature-gated steady-state thermal solve
                             aliases: heat, heat_flow

Mode-specific help:
  magneto2d help single
  magneto2d help field
  magneto2d help teaching
  magneto2d help thermal

The normal motor CLI also has sweep and batch command forms:
  magneto2d help sweep
  magneto2d help batch
"#
        }
        HelpTopic::Single => {
            r#"Usage:
  magneto2d FIXTURE --mesh-input MESH [--rotor-angle-deg DEG] [-o PATH]
  magneto2d FIXTURE --mode magnetostatic --mesh-input MESH [options]

Runs one 2D magnetostatic motor solve. Magnetostatic is the default mode, so
--mode magnetostatic is optional.

Inputs:
  FIXTURE                    Motor configuration JSON
  --mesh-input MESH          Backend-produced SolveMeshArtifact JSON

Options:
  --rotor-angle-deg DEG      Mechanical rotor angle (default: 0)
  --field-diagnostics        Emit high-volume airgap field diagnostics
  --assert-symmetry          Enable per-quadrant symmetry assertions
  -o PATH                    Write the solve_report JSON to PATH

Without -o, the JSON report is written to standard output.
"#
        }
        HelpTopic::Sweep => {
            r#"Usage:
  magneto2d FIXTURE --sweep [N] --mesh-input MESH [options]

Runs a fixed-mesh magnetostatic rotor sweep. The mesh artifact and rotor-motion
policy must permit reuse. The coilEM backend normally uses per-angle Gmsh
remeshing for public motor sweeps; see: magneto2d help batch.

Inputs:
  FIXTURE                    Motor configuration JSON
  --mesh-input MESH          Reusable SolveMeshArtifact JSON

Options:
  --sweep [N]                Number of positions (default: 18)
  --sweep-span-deg DEG       Electrical sweep span (default: 360)
  --workers N                Rayon worker threads
  --serial                   Use one worker when no override is set
  -o PATH                    Write the sweep_report JSON to PATH
"#
        }
        HelpTopic::Batch => {
            r#"Usage:
  magneto2d FIXTURE --batch-input BATCH [--workers N] [-o PATH]

Runs per-angle imported-mesh jobs. This is the command form used when each
rotor position has its own backend-produced Gmsh SolveMeshArtifact.

Inputs:
  FIXTURE                    Motor configuration JSON shared by all jobs
  --batch-input BATCH        JSON containing jobs with rotor_angle_deg and a
                             complete solve_mesh_artifact

Options:
  --workers N                Rayon worker threads
  --serial                   Use one worker when no override is set
  -o PATH                    Write the batch_solve_reports JSON to PATH
"#
        }
        HelpTopic::Field => {
            r#"Usage:
  magneto2d PROBLEM --mode field [-o PATH]

Solves a versioned magnetostatic_problem JSON containing a solve-ready P1
triangular mesh, materials, per-element sources, and explicit boundaries.
The document must declare units.length; coordinates are normalized to metres
exactly once at the input boundary. Nonlinear materials may select Picard or
damped Newton iteration; Newton can explicitly fall back to Picard.

Options:
  -o PATH                    Write field_solution_report JSON to PATH

Field mode does not accept --sweep, --mesh-input, or --batch-input.
"#
        }
        HelpTopic::Teaching => {
            r#"Usage:
  magneto2d REQUEST --mode teaching [-o PATH]

Runs a self-contained teaching field problem from a TeachingRequest JSON.
Teaching mode does not accept --sweep, --mesh-input, or --batch-input.

Options:
  -o PATH                    Write the teaching JSON report to PATH

Without -o, the JSON report is written to standard output.
"#
        }
        HelpTopic::Thermal => {
            r#"Usage:
  magneto2d REQUEST --mode thermal [-o PATH]

Runs the feature-gated steady-state thermal solver. Set
COILEM_THERMAL_ENABLED=1 before invoking this mode. Thermal mode does not
accept --sweep or --batch-input.

The public coilEM launch API rejects thermal requests; this compiled mode is
retained for future work and must not be presented as a public launch result.

Options:
  -o PATH                    Write the thermal_solve_report JSON to PATH
"#
        }
    }
}

pub fn apply_config_refinement_flags(config: &MotorConfig) {
    if let Some(preconditioner) = config
        .solve_params
        .as_ref()
        .and_then(|params| params.linear_solver_preconditioner.as_deref())
        .map(|value| value.trim().to_ascii_lowercase())
        .filter(|value| value == "ic0" || value == "jacobi")
    {
        env::set_var("MAGNETO2D_PCG_PRECONDITIONER", &preconditioner);
        eprintln!("magneto2d: pcg_preconditioner={preconditioner}");
    }

    let _ = config;
}

fn truthy_env_value(value: Option<&str>) -> bool {
    value.map(truthy_value).unwrap_or(false)
}

fn truthy_value(value: &str) -> bool {
    let normalized = value.trim().to_ascii_lowercase();
    !normalized.is_empty()
        && normalized != "0"
        && normalized != "false"
        && normalized != "no"
        && normalized != "off"
}

#[cfg(test)]
mod tests {
    use super::{help_text, CliEnvironment, CliOptions, HelpTopic, DEFAULT_FIXTURE};

    fn empty_env() -> CliEnvironment {
        CliEnvironment::default()
    }

    #[test]
    fn cli_defaults_match_imported_mesh_surface() {
        let options = CliOptions::from_args_and_env(Vec::<String>::new(), empty_env()).unwrap();

        assert!(!options.show_help);
        assert_eq!(options.help_topic, HelpTopic::Overview);
        assert!(!options.sweep_mode);
        assert!(!options.serial);
        assert_eq!(options.workers, None);
        assert_eq!(options.effective_workers(), None);
        assert_eq!(options.n_positions, 18);
        assert_eq!(options.sweep_span_deg, None);
        assert_eq!(options.rotor_angle_deg, 0.0);
        assert_eq!(options.input_path, DEFAULT_FIXTURE);
        assert_eq!(options.mesh_input_path, None);
        assert_eq!(options.batch_input_path, None);
        assert_eq!(options.output_path, None);
        assert!(!options.field_diagnostics);
        assert!(!options.assert_symmetry);
        assert_eq!(options.solve_mode, super::SolveMode::Magnetostatic);
    }

    #[test]
    fn cli_parses_help_without_enabling_work() {
        let options = CliOptions::from_args_and_env(["--help"], empty_env()).unwrap();

        assert!(options.show_help);
        assert_eq!(options.help_topic, HelpTopic::Overview);
        assert!(!options.sweep_mode);
        assert_eq!(options.input_path, DEFAULT_FIXTURE);

        let short = CliOptions::from_args_and_env(["-h", "fixture.json"], empty_env()).unwrap();
        assert!(short.show_help);
        assert_eq!(short.input_path, "fixture.json");
    }

    #[test]
    fn cli_parses_named_and_contextual_help_topics() {
        let modes = CliOptions::from_args_and_env(["help", "modes"], empty_env()).unwrap();
        assert!(modes.show_help);
        assert_eq!(modes.help_topic, HelpTopic::Modes);

        let single =
            CliOptions::from_args_and_env(["--mode", "magnetostatic", "--help"], empty_env())
                .unwrap();
        assert!(single.show_help);
        assert_eq!(single.help_topic, HelpTopic::Single);

        let teaching =
            CliOptions::from_args_and_env(["--mode", "teaching", "--help"], empty_env()).unwrap();
        assert_eq!(teaching.help_topic, HelpTopic::Teaching);

        let field =
            CliOptions::from_args_and_env(["--mode", "field", "--help"], empty_env()).unwrap();
        assert_eq!(field.help_topic, HelpTopic::Field);

        let thermal =
            CliOptions::from_args_and_env(["--mode", "thermal", "--help"], empty_env()).unwrap();
        assert_eq!(thermal.help_topic, HelpTopic::Thermal);

        let sweep = CliOptions::from_args_and_env(["--sweep", "--help"], empty_env()).unwrap();
        assert_eq!(sweep.help_topic, HelpTopic::Sweep);

        let batch =
            CliOptions::from_args_and_env(["--batch-input", "batch.json", "--help"], empty_env())
                .unwrap();
        assert_eq!(batch.help_topic, HelpTopic::Batch);
    }

    #[test]
    fn cli_mode_help_lists_values_instead_of_parsing_help_as_a_mode() {
        let options = CliOptions::from_args_and_env(["--mode", "--help"], empty_env()).unwrap();
        assert!(options.show_help);
        assert_eq!(options.help_topic, HelpTopic::Modes);

        let alias = CliOptions::from_args_and_env(["--mode", "help"], empty_env()).unwrap();
        assert!(alias.show_help);
        assert_eq!(alias.help_topic, HelpTopic::Modes);
    }

    #[test]
    fn cli_rejects_unknown_or_extra_help_topics() {
        let unknown = CliOptions::from_args_and_env(["help", "unknown"], empty_env())
            .expect_err("unknown help topic should fail");
        assert!(unknown.contains("expected modes|single|sweep|batch|field|teaching|thermal"));

        let extra = CliOptions::from_args_and_env(["help", "sweep", "extra"], empty_env())
            .expect_err("help should accept one topic");
        assert!(extra.contains("help accepts at most one topic"));
    }

    #[test]
    fn help_topics_explain_their_valid_options() {
        assert!(help_text(HelpTopic::Overview).contains("magneto2d help [TOPIC]"));
        assert!(help_text(HelpTopic::Modes).contains("Valid MODE values"));
        assert!(help_text(HelpTopic::Single).contains("--rotor-angle-deg"));
        assert!(help_text(HelpTopic::Sweep).contains("--sweep-span-deg"));
        assert!(help_text(HelpTopic::Batch).contains("--batch-input"));
        assert!(help_text(HelpTopic::Field).contains("magnetostatic_problem"));
        assert!(help_text(HelpTopic::Teaching).contains("TeachingRequest"));
        assert!(help_text(HelpTopic::Thermal).contains("COILEM_THERMAL_ENABLED=1"));
    }

    #[test]
    fn cli_preserves_worker_precedence_and_serial_fallback() {
        let serial_only = CliOptions::from_args_and_env(["--serial"], empty_env()).unwrap();
        assert_eq!(serial_only.effective_workers(), Some(1));

        let env_worker = CliOptions::from_args_and_env(
            ["--serial"],
            CliEnvironment {
                workers: Some("8".to_string()),
                ..empty_env()
            },
        )
        .unwrap();
        assert_eq!(env_worker.workers, Some(8));
        assert_eq!(env_worker.effective_workers(), Some(8));

        let cli_worker = CliOptions::from_args_and_env(
            ["--workers", "2"],
            CliEnvironment {
                workers: Some("8".to_string()),
                ..empty_env()
            },
        )
        .unwrap();
        assert_eq!(cli_worker.effective_workers(), Some(2));

        let ignored_zero = CliOptions::from_args_and_env(
            ["--workers", "0"],
            CliEnvironment {
                workers: Some("8".to_string()),
                ..empty_env()
            },
        )
        .unwrap();
        assert_eq!(ignored_zero.effective_workers(), Some(8));
    }

    #[test]
    fn cli_parses_sweep_and_output_options_without_policy_changes() {
        let options = CliOptions::from_args_and_env(
            [
                "--sweep",
                "48",
                "--sweep-span-deg",
                "60",
                "--rotor-angle-deg",
                "15",
                "--mesh-input",
                "mesh.json",
                "--batch-input",
                "batch.json",
                "--field-diagnostics",
                "--assert-symmetry",
                "-o",
                "out.json",
                "fixture.json",
            ],
            empty_env(),
        )
        .unwrap();

        assert!(options.sweep_mode);
        assert_eq!(options.n_positions, 48);
        assert_eq!(options.sweep_span_deg, Some(60.0));
        assert_eq!(options.rotor_angle_deg, 15.0);
        assert_eq!(options.mesh_input_path, Some("mesh.json".to_string()));
        assert_eq!(options.batch_input_path, Some("batch.json".to_string()));
        assert!(options.field_diagnostics);
        assert!(options.assert_symmetry);
        assert_eq!(options.output_path, Some("out.json".to_string()));
        assert_eq!(options.input_path, "fixture.json");
    }

    #[test]
    fn cli_preserves_existing_parse_errors() {
        let err = CliOptions::from_args_and_env(["--workers", "many"], empty_env())
            .expect_err("invalid workers should fail");
        assert!(err.contains("invalid --workers value 'many'"));

        let err = CliOptions::from_args_and_env(["--sweep-span-deg", "wide"], empty_env())
            .expect_err("invalid sweep span should fail");
        assert!(err.contains("invalid --sweep-span-deg"));
    }

    #[test]
    fn cli_rejects_removed_native_mesher_flags() {
        let err = CliOptions::from_args_and_env(["--mesh-only"], empty_env())
            .expect_err("mesh-only preview should be a backend Gmsh path");
        assert!(err.contains("--mesh-only was removed"), "{err}");

        let err = CliOptions::from_args_and_env(["--mesher", "gmsh"], empty_env())
            .expect_err("mesher selection should not be a Rust CLI path");
        assert!(err.contains("--mesher was removed"), "{err}");
        assert!(err.contains("gmsh"), "{err}");
    }
}
