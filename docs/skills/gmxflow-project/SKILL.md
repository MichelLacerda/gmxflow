---
name: gmxflow-project
description: Maintain and extend the gmxflow molecular-dynamics workflow project. Use for changes to its Python package, GROMACS pipeline, configuration, force-field handling, tests, or user documentation; not for unrelated scientific questions or general GROMACS usage.
metadata:
  short-description: Project-specific guidance for gmxflow
---

# gmxflow Project Skill

Use this skill when working in this repository. Treat source code and tests as the authority for implemented behavior; docs describe user-facing workflows, while the roadmap may contain plans that are not implemented.

## Project context

- `gmxflow` is a Python package (Python `>=3.12`) for preparing, running, and analyzing molecular-dynamics workflows using GROMACS.
- The current public interface is a Typer CLI (`gmxflow.cli:app`). A stable scientist-oriented Python API and guided Jupyter experience are planned, not implemented. Do not invent or document planned classes/methods as working functionality.
- User-facing installation prioritizes Conda/Micromamba environments containing Python, `gmxflow`, and an accessible GROMACS executable. `uv` is the current developer workflow; do not present it as a requirement for end users.
- Scientific scope is limited: protein–peptide workflows are the primary path; small molecules require externally prepared CGenFF-compatible inputs and force-field parameters. Avoid implying universal preparation or parameterization.

## Technical conventions

- Follow the existing `src/gmxflow/` package layout and keep CLI orchestration in `cli.py`; place reusable behavior in domain modules rather than making it depend on Typer or console output.
- Configuration is TOML validated with Pydantic in `config.py`. Keep generated defaults, validation, documentation, and tests consistent when changing the schema. Resolve project-relative inputs against the configuration/project location as established in the implementation.
- GROMACS commands are executed as argument sequences through the existing runner/executor; do not introduce shell-string execution. Preserve per-step logs, resumability/state fingerprints, and dry-run behavior when changing pipeline execution.
- Pipeline definitions and step dependencies belong in `pipeline.py`; preserve step names and dependencies used by `--from-step`, `--until`, and persisted state unless a migration or compatibility change is intentional.
- Generated and regenerable data belongs in project `work/` and `outputs/`, not in source directories. Avoid overwriting user inputs or existing project data implicitly; retain explicit force/overwrite behavior.
- External force fields are user-level shared data, not duplicated into each project. Respect `GMXFLOW_FORCEFIELD_DIR`, `XDG_DATA_HOME` (Linux/macOS), and the platform-specific default. Preserve resolver precedence and the no-implicit-overwrite rule in `forcefields.py`.
- Treat scientific outputs and claims carefully. Keep `smoke` runs clearly identified as integration checks, not scientifically interpretable simulations. Do not silently alter force-field, protonation, sampling, GPU, or analysis assumptions.
- Keep user documentation accessible to scientists with limited programming experience: lead with the supported workflow, explain required inputs and expected outputs, and make optional/developer-only steps explicit.

## Working on changes

1. Inspect the relevant implementation, tests, and documentation before editing. For behavior changes, derive the contract from code and tests; use the roadmap only to understand intent.
2. Make the smallest coherent change. When adding or changing behavior, update focused tests and relevant docs/examples in the same change.
3. Prefer tests that verify outcomes and safety properties: config validation, command construction, pipeline state/resume behavior, file placement, and clear failures. Do not require a GPU or a full production simulation for ordinary unit tests.
4. Run focused tests first, then the project checks appropriate to the change. The documented developer commands are `uv run pytest`, `uv run ruff check .`, and `uv run mypy src`; if `uv` is unavailable, use the active project environment’s equivalent commands and report what was run.
5. Review the final diff for unintended changes and whitespace errors. Preserve unrelated user changes and untracked files.

## Relevant references

Read only the references needed for the task:

- Installation and Conda/Micromamba/Jupyter user workflow: [`docs/how-to/install-gmxflow-without-uv.md`](../../how-to/install-gmxflow-without-uv.md).
- Configuration schema and meanings: [`docs/reference/config.md`](../../reference/config.md) and `src/gmxflow/config.py`.
- GROMACS/CUDA environment setup: [`docs/how-to/install-gromacs-cuda.md`](../../how-to/install-gromacs-cuda.md).
- CGenFF inputs, force-field installation, and scientific caveats: [`docs/how-to/cgenff-paramchem.md`](../../how-to/cgenff-paramchem.md), `src/gmxflow/forcefields.py`, and `src/gmxflow/ligand.py`.
- Current implemented scope versus future work: [`ROADMAP.md`](../../../ROADMAP.md).
- User-facing workflows and sample project: [`docs/tutorials/protein-ligand-complex.md`](../../tutorials/protein-ligand-complex.md) and `examples/`.
