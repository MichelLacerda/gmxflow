from pathlib import Path

import pytest
from pydantic import ValidationError

from gmxflow.config import GmxFlowConfig, default_config, load_config, to_toml


def test_default_config_uses_project_name() -> None:
    config = default_config("mastoparan_dm")

    assert config.project.name == "mastoparan_dm"
    assert config.project.description == "Simulação de dinâmica molecular com GROMACS"


def test_simulation_step_calculation_defaults() -> None:
    config = GmxFlowConfig()

    assert config.simulation.production_steps == 50_000_000
    assert config.simulation.nvt_steps == 50_000
    assert config.simulation.npt_steps == 50_000


def test_smoke_profile_uses_tiny_step_counts() -> None:
    config = GmxFlowConfig.model_validate({"simulation": {"profile": "smoke"}})

    assert config.simulation.production_steps == 10
    assert config.simulation.nvt_steps == 10
    assert config.simulation.npt_steps == 10


def test_config_round_trip_through_toml(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(to_toml(default_config("roundtrip")), encoding="utf-8")

    loaded = load_config(config_path)

    assert loaded.project.name == "roundtrip"
    assert loaded.input.receptor_pdb == "inputs/receptor.pdb"
    assert loaded.solvent.neutralize is True
    assert loaded.plots.receptor_color == "#1f77b4"
    assert loaded.plots.ligand_color == "#C2185B"


def test_generated_toml_documents_advanced_paths_without_enabling_them() -> None:
    toml = to_toml(default_config("paths_doc"))

    assert "# [paths]" in toml
    assert '# work_dir = "work"' in toml
    assert "\n[paths]\n" not in toml
    assert "\n[plots]\n" in toml
    assert 'receptor_color = "#1f77b4"' in toml


def test_invalid_ph_is_rejected() -> None:
    with pytest.raises(ValidationError):
        GmxFlowConfig.model_validate({"input": {"ph": 15}})


def test_smoke_example_config_is_valid() -> None:
    config = load_config(Path("examples/smoke_peptide_complex/config.toml"))

    assert config.project.name == "smoke_peptide_complex"
    assert config.simulation.profile == "smoke"
    assert config.simulation.production_steps == 10
