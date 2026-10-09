#![allow(
    clippy::too_many_arguments,
    clippy::needless_range_loop,
    clippy::type_complexity,
    clippy::wrong_self_convention,
    clippy::manual_is_multiple_of,
    clippy::manual_div_ceil,
    clippy::if_same_then_else,
    clippy::question_mark,
    clippy::needless_lifetimes,
    clippy::unnecessary_lazy_evaluations
)]

mod assembly;
pub mod field;
mod magnet_fraction;
mod materials;
mod mesh;
mod motor;
mod postprocess;
mod run_config;
mod schema;
mod solve;
mod sources;
mod sparse;
mod teaching;
mod thermal;

use std::{fs, path::Path};

use motor::MotorConfig;
use run_config::{help_text, thermal_mode_enabled_from_env, CliOptions, SolveMode};
use schema::{
    render_enveloped, KIND_BATCH_SOLVE_REPORTS, KIND_FIELD_SOLUTION_REPORT, KIND_SOLVE_REPORT,
    KIND_SWEEP_REPORT, KIND_THERMAL_SOLVE_REPORT,
};

/// Execute the Magneto2D binary adapter with arguments that exclude the
/// executable name. The reusable field API lives in [`field`]; this function
/// intentionally owns process environment, filesystem, CLI, and legacy motor
/// report concerns.
pub fn run_cli<I>(args: I) -> Result<(), Box<dyn std::error::Error>>
where
    I: IntoIterator<Item = String>,
{
    let options = CliOptions::from_process_args(args)?;
    if options.show_help {
        println!("{}", help_text(options.help_topic));
        return Ok(());
    }
    options.apply_process_flags();

    if options.solve_mode == SolveMode::Field {
        if options.sweep_mode
            || options.batch_input_path.is_some()
            || options.mesh_input_path.is_some()
        {
            return Err("field mode does not support sweep, batch, or motor mesh inputs".into());
        }
        let raw = fs::read_to_string(&options.input_path)?;
        let document: field::FieldProblemDocument = serde_json::from_str(&raw)?;
        let problem = document.into_problem()?;
        eprintln!("magneto2d: generic field solve ({})", options.input_path);
        let solution = field::solve(&problem)?;
        for warning in &solution.warnings {
            eprintln!("magneto2d: warning: {warning}");
        }
        let report = field::FieldSolutionReport {
            problem_kind: field::MAGNETOSTATIC_PROBLEM_KIND.to_string(),
            problem_version: field::MAGNETOSTATIC_PROBLEM_VERSION.to_string(),
            normalized_length_unit: "m".to_string(),
            solution,
        };
        let rendered = render_enveloped(
            KIND_FIELD_SOLUTION_REPORT,
            Some(options.input_path.as_str()),
            report,
        )?;
        return write_rendered(&options.output_path, &rendered);
    }

    if options.solve_mode == SolveMode::Thermal {
        if !thermal_mode_enabled_from_env() {
            return Err(
                "--mode thermal requires COILEM_THERMAL_ENABLED=1".into(),
            );
        }
        if options.sweep_mode || options.batch_input_path.is_some() {
            return Err("thermal mode does not support --sweep or --batch-input yet".into());
        }
        let raw = fs::read_to_string(&options.input_path)?;
        let request: thermal::solve::ThermalCliInput = serde_json::from_str(&raw)?;
        eprintln!(
            "magneto2d: thermal steady-state solve ({})",
            options.input_path
        );
        let report = thermal::run_steady_state_thermal(&request.into_request()?)?;
        let rendered = render_enveloped(
            KIND_THERMAL_SOLVE_REPORT,
            Some(options.input_path.as_str()),
            report,
        )?;
        return write_rendered(&options.output_path, &rendered);
    }

    if options.solve_mode == SolveMode::Teaching {
        if options.sweep_mode
            || options.batch_input_path.is_some()
            || options.mesh_input_path.is_some()
        {
            return Err(
                "teaching mode does not support sweep, batch, or imported mesh inputs".into(),
            );
        }
        let raw = fs::read_to_string(&options.input_path)?;
        let request: teaching::TeachingRequest = serde_json::from_str(&raw)?;
        eprintln!("magneto2d: teaching field solve ({})", options.input_path);
        let report = teaching::run(request)?;
        let rendered = serde_json::to_string_pretty(&report)?;
        return write_rendered(&options.output_path, &rendered);
    }

    let raw = fs::read_to_string(&options.input_path)?;
    let config: MotorConfig = serde_json::from_str(&raw)?;
    config.validate()?;
    run_config::apply_config_refinement_flags(&config);
    let solve_mesh_artifact = if let Some(path) = options.mesh_input_path.as_deref() {
        let mesh_raw = fs::read_to_string(path)?;
        let solve_mesh_artifact: solve::SolveMeshArtifact = serde_json::from_str(&mesh_raw)?;
        Some(solve_mesh_artifact)
    } else {
        None
    };
    let batch_input = if let Some(path) = options.batch_input_path.as_deref() {
        let batch_raw = fs::read_to_string(path)?;
        let batch_input: solve::ImportedMeshBatchInput = serde_json::from_str(&batch_raw)?;
        Some(batch_input)
    } else {
        None
    };

    eprintln!(
        "magneto2d: loading {} ({})",
        options.input_path, config.topology
    );

    let fixture_path = Some(options.input_path.as_str());
    let rendered = if let Some(batch_input) = batch_input {
        let report = solve::run_imported_mesh_batch_with_workers(
            &config,
            batch_input,
            options.effective_workers(),
        )?;
        render_enveloped(KIND_BATCH_SOLVE_REPORTS, fixture_path, report)?
    } else if options.sweep_mode {
        let report = solve::run_rotor_sweep_with_mesh_and_workers(
            &config,
            options.n_positions,
            options.sweep_span_deg,
            options.effective_workers(),
            solve_mesh_artifact,
        )?;
        render_enveloped(KIND_SWEEP_REPORT, fixture_path, report)?
    } else {
        let rotor_angle_rad = options.rotor_angle_rad();
        let report = solve::run_magnetostatic_solve_at_angle_with_mesh(
            &config,
            rotor_angle_rad,
            solve_mesh_artifact,
        )?;
        render_enveloped(KIND_SOLVE_REPORT, fixture_path, report)?
    };

    write_rendered(&options.output_path, &rendered)
}

fn write_rendered(
    output_path: &Option<String>,
    rendered: &str,
) -> Result<(), Box<dyn std::error::Error>> {
    if let Some(path) = output_path {
        if let Some(parent) = Path::new(path).parent() {
            if !parent.as_os_str().is_empty() {
                fs::create_dir_all(parent)?;
            }
        }
        fs::write(path, rendered.as_bytes())?;
        eprintln!("magneto2d: wrote report to {}", path);
    } else {
        println!("{rendered}");
    }
    Ok(())
}
