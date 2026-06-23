from pathlib import Path

import pytest

from gmxflow.config import default_config
from gmxflow.executor import select_steps
from gmxflow.pipeline import build_pipeline


def test_build_pipeline_returns_expected_order(tmp_path: Path) -> None:
    steps = build_pipeline(default_config("order_test"), config_dir=tmp_path)

    assert [step.name for step in steps[:5]] == [
        "prepare",
        "topology",
        "box",
        "solvate",
        "ions-grompp",
    ]
    assert steps[-1].name == "report"


def test_topology_command_uses_force_field_and_water(tmp_path: Path) -> None:
    config = default_config("topology_test")
    config.force_field.name = "amber99sb-ildn"
    config.force_field.water = "tip3p"

    steps = build_pipeline(config, config_dir=tmp_path)
    topology = next(step for step in steps if step.name == "topology")

    assert topology.command[:2] == ["gmx", "pdb2gmx"]
    assert topology.command[topology.command.index("-ff") + 1] == "amber99sb-ildn"
    assert topology.command[topology.command.index("-water") + 1] == "tip3p"
    assert topology.outputs == [
        tmp_path.resolve() / "work" / "topo" / "complexo.gro",
        tmp_path.resolve() / "work" / "topo" / "topol.top",
        tmp_path.resolve() / "work" / "topo" / "topol_Protein_chain_A.itp",
        tmp_path.resolve() / "work" / "topo" / "topol_Protein_chain_B.itp",
        tmp_path.resolve() / "work" / "topo" / "posre_Protein_chain_A.itp",
        tmp_path.resolve() / "work" / "topo" / "posre_Protein_chain_B.itp",
    ]


def test_gromacs_steps_use_gmxlib_for_project_force_field(tmp_path: Path) -> None:
    config = default_config("local_force_field_test")
    config.force_field.name = "charmm36-feb2026_cgenff-5.0"
    (tmp_path / "charmm36-feb2026_cgenff-5.0.ff").mkdir()

    steps = build_pipeline(config, config_dir=tmp_path)
    topology = next(step for step in steps if step.name == "topology")
    em_grompp = next(step for step in steps if step.name == "em-grompp")

    assert topology.env == {"GMXLIB": str(tmp_path.resolve())}
    assert em_grompp.env == {"GMXLIB": str(tmp_path.resolve())}


def test_gromacs_steps_do_not_set_gmxlib_for_installed_force_field(tmp_path: Path) -> None:
    config = default_config("installed_force_field_test")
    config.force_field.name = "amber99sb-ildn"

    steps = build_pipeline(config, config_dir=tmp_path)
    topology = next(step for step in steps if step.name == "topology")

    assert topology.env == {}


def test_prepare_step_uses_internal_cli_command(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"

    steps = build_pipeline(default_config("prepare_test"), config_dir=tmp_path, config_path=config_path)
    prepare = steps[0]

    assert prepare.command == [
        "gmxflow",
        "prepare-complex",
        "--config",
        str(config_path.resolve()),
        "--force",
    ]


def test_small_molecule_pipeline_adds_ligand_topology_step(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config = default_config("small_molecule_test")
    config.input.ligand_kind = "small_molecule"
    config.input.ligand_mol2 = "inputs/jz4.mol2"
    config.input.ligand_str = "inputs/jz4.str"
    config.input.ligand_resname = "JZ4"

    steps = build_pipeline(config, config_dir=tmp_path, config_path=config_path)

    project_root = tmp_path.resolve()
    assert [step.name for step in steps[:7]] == [
        "prepare",
        "ligand-topology",
        "protein-topology",
        "assemble-complex",
        "box",
        "solvate",
        "ions-grompp",
    ]
    assert "topology" not in [step.name for step in steps]
    assert steps[-1].name == "report"
    ligand_topology = steps[1]
    assert ligand_topology.command == [
        "gmxflow",
        "prepare-ligand",
        "--config",
        str(config_path.resolve()),
    ]
    assert ligand_topology.inputs == [
        project_root / "inputs" / "jz4.mol2",
        project_root / "inputs" / "jz4.str",
    ]
    assert ligand_topology.outputs == [
        project_root / "work" / "ligand" / "jz4.itp",
        project_root / "work" / "ligand" / "jz4.prm",
        project_root / "work" / "ligand" / "jz4.top",
        project_root / "work" / "ligand" / "jz4_ini.pdb",
    ]
    protein_topology = steps[2]
    assert protein_topology.command == [
        "gmx",
        "pdb2gmx",
        "-f",
        str(project_root / "work" / "prep" / "receptor_fixed.pdb"),
        "-o",
        "protein.gro",
        "-p",
        "topol.top",
        "-i",
        "posre.itp",
        "-ff",
        "amber99sb-ildn",
        "-water",
        "tip3p",
        "-ignh",
        "-ter",
    ]
    assert protein_topology.stdin == "0\n0\n"
    assert protein_topology.inputs == [
        project_root / "work" / "prep" / "receptor_fixed.pdb"
    ]
    assert protein_topology.outputs == [
        project_root / "work" / "topo" / "protein.gro",
        project_root / "work" / "topo" / "topol.top",
    ]
    assemble_complex = steps[3]
    assert assemble_complex.command == [
        "gmxflow",
        "assemble-complex",
        "--config",
        str(config_path.resolve()),
    ]
    assert assemble_complex.inputs == [
        project_root / "work" / "topo" / "protein.gro",
        project_root / "work" / "topo" / "topol.top",
        project_root / "work" / "ligand" / "jz4.itp",
        project_root / "work" / "ligand" / "jz4.prm",
        project_root / "work" / "ligand" / "jz4_ini.pdb",
    ]
    assert assemble_complex.outputs == [
        project_root / "work" / "topo" / "complexo.gro",
        project_root / "work" / "topo" / "topol.top",
        project_root / "work" / "topo" / ".small_molecule_complex.ok",
    ]


def test_charmm_small_molecule_protein_topology_selects_standard_termini(
    tmp_path: Path,
) -> None:
    config = default_config("charmm_termini_test")
    config.input.ligand_kind = "small_molecule"
    config.input.ligand_mol2 = "inputs/jz4.mol2"
    config.input.ligand_str = "inputs/jz4.str"
    config.force_field.name = "charmm36-feb2026_cgenff-5.0"

    steps = build_pipeline(config, config_dir=tmp_path)
    protein_topology = next(step for step in steps if step.name == "protein-topology")

    assert protein_topology.stdin == "1\n0\n"


def test_charmm_peptide_topology_selects_standard_termini_for_two_chains(
    tmp_path: Path,
) -> None:
    config = default_config("charmm_peptide_termini_test")
    config.force_field.name = "charmm36-feb2026_cgenff-5.0"

    steps = build_pipeline(config, config_dir=tmp_path)
    topology = next(step for step in steps if step.name == "topology")

    assert topology.stdin == "1\n0\n1\n0\n"


def test_pdb2gmx_terminal_selections_override_auto_policy(tmp_path: Path) -> None:
    config = default_config("custom_termini_test")
    config.force_field.name = "charmm36-feb2026_cgenff-5.0"
    config.pdb2gmx.terminal_selections = ["8", "7"]

    steps = build_pipeline(config, config_dir=tmp_path)
    topology = next(step for step in steps if step.name == "topology")

    assert topology.stdin == "8\n7\n"


def test_small_molecule_strict_inputs_requires_mol2_and_stream(
    tmp_path: Path,
) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "receptor.pdb").write_text("ATOM\n", encoding="utf-8")
    (inputs / "ligante.pdb").write_text("HETATM\n", encoding="utf-8")
    config = default_config("small_molecule_strict_test")
    config.input.ligand_kind = "small_molecule"
    config.input.ligand_mol2 = "inputs/jz4.mol2"
    config.input.ligand_str = "inputs/jz4.str"

    with pytest.raises(FileNotFoundError, match="jz4.mol2"):
        build_pipeline(config, config_dir=tmp_path, strict_inputs=True)


def test_em_grompp_uses_topology_from_topo_directory(tmp_path: Path) -> None:
    steps = build_pipeline(default_config("em_grompp_test"), config_dir=tmp_path)
    em_grompp = next(step for step in steps if step.name == "em-grompp")

    project_root = tmp_path.resolve()
    assert em_grompp.command[em_grompp.command.index("-p") + 1] == str(
        project_root / "work" / "topo" / "topol.top"
    )
    assert project_root / "work" / "topo" / "topol.top" in em_grompp.inputs
    assert em_grompp.outputs == [
        project_root / "work" / "em" / "em.tpr",
        project_root / "work" / "em" / "mdout.mdp",
    ]


def test_solvate_uses_internal_topology_reset_command(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    steps = build_pipeline(default_config("solvate_test"), config_dir=tmp_path, config_path=config_path)
    solvate = next(step for step in steps if step.name == "solvate")

    assert solvate.command == [
        "gmxflow",
        "solvate-system",
        "--config",
        str(config_path.resolve()),
    ]


def test_nvt_grompp_uses_topology_from_topo_directory(tmp_path: Path) -> None:
    steps = build_pipeline(default_config("nvt_grompp_test"), config_dir=tmp_path)
    nvt_grompp = next(step for step in steps if step.name == "nvt-grompp")

    project_root = tmp_path.resolve()
    assert nvt_grompp.command[nvt_grompp.command.index("-p") + 1] == str(
        project_root / "work" / "topo" / "topol.top"
    )
    assert project_root / "work" / "topo" / "topol.top" in nvt_grompp.inputs
    assert nvt_grompp.outputs == [
        project_root / "work" / "nvt" / "nvt.tpr",
        project_root / "work" / "nvt" / "mdout.mdp",
    ]


def test_nvt_mdrun_outputs_restartable_artifacts(tmp_path: Path) -> None:
    steps = build_pipeline(default_config("nvt_test"), config_dir=tmp_path)
    nvt = next(step for step in steps if step.name == "nvt")

    project_root = tmp_path.resolve()
    assert nvt.command[:4] == ["gmx", "mdrun", "-v", "-deffnm"]
    assert nvt.command[nvt.command.index("-deffnm") + 1] == "nvt"
    assert nvt.inputs == [project_root / "work" / "nvt" / "nvt.tpr"]
    assert nvt.outputs == [
        project_root / "work" / "nvt" / "nvt.gro",
        project_root / "work" / "nvt" / "nvt.cpt",
        project_root / "work" / "nvt" / "nvt.edr",
        project_root / "work" / "nvt" / "nvt.log",
        project_root / "work" / "nvt" / "nvt.trr",
    ]


def test_npt_grompp_uses_topology_from_topo_directory(tmp_path: Path) -> None:
    steps = build_pipeline(default_config("npt_grompp_test"), config_dir=tmp_path)
    npt_grompp = next(step for step in steps if step.name == "npt-grompp")

    project_root = tmp_path.resolve()
    assert npt_grompp.command[npt_grompp.command.index("-p") + 1] == str(
        project_root / "work" / "topo" / "topol.top"
    )
    assert project_root / "work" / "topo" / "topol.top" in npt_grompp.inputs
    assert npt_grompp.outputs == [
        project_root / "work" / "npt" / "npt.tpr",
        project_root / "work" / "npt" / "mdout.mdp",
    ]


def test_npt_mdrun_outputs_restartable_artifacts(tmp_path: Path) -> None:
    steps = build_pipeline(default_config("npt_test"), config_dir=tmp_path)
    npt = next(step for step in steps if step.name == "npt")

    project_root = tmp_path.resolve()
    assert npt.command[:4] == ["gmx", "mdrun", "-v", "-deffnm"]
    assert npt.command[npt.command.index("-deffnm") + 1] == "npt"
    assert npt.inputs == [project_root / "work" / "npt" / "npt.tpr"]
    assert npt.outputs == [
        project_root / "work" / "npt" / "npt.gro",
        project_root / "work" / "npt" / "npt.cpt",
        project_root / "work" / "npt" / "npt.edr",
        project_root / "work" / "npt" / "npt.log",
        project_root / "work" / "npt" / "npt.trr",
    ]


def test_production_grompp_uses_topology_from_topo_directory(tmp_path: Path) -> None:
    steps = build_pipeline(default_config("production_grompp_test"), config_dir=tmp_path)
    production_grompp = next(step for step in steps if step.name == "production-grompp")

    project_root = tmp_path.resolve()
    assert production_grompp.command[production_grompp.command.index("-p") + 1] == str(
        project_root / "work" / "topo" / "topol.top"
    )
    assert project_root / "work" / "topo" / "topol.top" in production_grompp.inputs
    assert production_grompp.outputs == [
        project_root / "work" / "prod" / "md.tpr",
        project_root / "work" / "prod" / "mdout.mdp",
    ]


def test_production_mdrun_honors_gpu_off(tmp_path: Path) -> None:
    config = default_config("cpu_test")
    config.mdrun.gpu = "off"

    steps = build_pipeline(config, config_dir=tmp_path)
    production = next(step for step in steps if step.name == "production")

    assert production.command == ["gmx", "mdrun", "-v", "-deffnm", "md", "-ntmpi", "1", "-ntomp", "8", "-nb", "cpu"]


def test_production_mdrun_outputs_restartable_artifacts(tmp_path: Path) -> None:
    steps = build_pipeline(default_config("production_test"), config_dir=tmp_path)
    production = next(step for step in steps if step.name == "production")

    project_root = tmp_path.resolve()
    assert production.inputs == [project_root / "work" / "prod" / "md.tpr"]
    assert production.outputs == [
        project_root / "work" / "prod" / "md.xtc",
        project_root / "work" / "prod" / "md.gro",
        project_root / "work" / "prod" / "md.cpt",
        project_root / "work" / "prod" / "md.edr",
        project_root / "work" / "prod" / "md.log",
    ]


def test_pbc_nojump_uses_production_trajectory(tmp_path: Path) -> None:
    steps = build_pipeline(default_config("pbc_nojump_test"), config_dir=tmp_path)
    pbc_nojump = next(step for step in steps if step.name == "pbc-nojump")

    project_root = tmp_path.resolve()
    assert pbc_nojump.command == [
        "gmx",
        "trjconv",
        "-s",
        "md.tpr",
        "-f",
        "md.xtc",
        "-o",
        "md_nojump.xtc",
        "-pbc",
        "nojump",
    ]
    assert pbc_nojump.stdin == "0\n"
    assert pbc_nojump.inputs == [
        project_root / "work" / "prod" / "md.tpr",
        project_root / "work" / "prod" / "md.xtc",
    ]
    assert pbc_nojump.outputs == [
        project_root / "work" / "prod" / "md_nojump.xtc"
    ]


def test_pbc_center_uses_configured_groups(tmp_path: Path) -> None:
    config = default_config("pbc_center_test")
    config.analysis.center_group = "Protein"
    config.analysis.output_group = "System"

    steps = build_pipeline(config, config_dir=tmp_path)
    pbc_center = next(step for step in steps if step.name == "pbc-center")

    project_root = tmp_path.resolve()
    assert pbc_center.command == [
        "gmx",
        "trjconv",
        "-s",
        "md.tpr",
        "-f",
        "md_nojump.xtc",
        "-o",
        "md_nopbc.xtc",
        "-pbc",
        "mol",
        "-center",
        "-ur",
        "compact",
    ]
    assert pbc_center.stdin == "Protein\nSystem\n"
    assert pbc_center.inputs == [
        project_root / "work" / "prod" / "md.tpr",
        project_root / "work" / "prod" / "md_nojump.xtc",
    ]
    assert pbc_center.outputs == [
        project_root / "work" / "prod" / "md_nopbc.xtc"
    ]


def test_fit_uses_configured_groups(tmp_path: Path) -> None:
    config = default_config("fit_test")
    config.analysis.fit_group = "Backbone"
    config.analysis.output_group = "System"

    steps = build_pipeline(config, config_dir=tmp_path)
    fit = next(step for step in steps if step.name == "fit")

    project_root = tmp_path.resolve()
    assert fit.command == [
        "gmx",
        "trjconv",
        "-s",
        "md.tpr",
        "-f",
        "md_nopbc.xtc",
        "-o",
        "md_fit.xtc",
        "-fit",
        "rot+trans",
    ]
    assert fit.stdin == "Backbone\nSystem\n"
    assert fit.inputs == [
        project_root / "work" / "prod" / "md.tpr",
        project_root / "work" / "prod" / "md_nopbc.xtc",
    ]
    assert fit.outputs == [project_root / "work" / "prod" / "md_fit.xtc"]


def test_mdrun_does_not_add_ntmpi_for_mpi_engine(tmp_path: Path) -> None:
    config = default_config("mpi_test")
    config.mdrun.engine = "gmx_mpi"

    steps = build_pipeline(config, config_dir=tmp_path)
    em = next(step for step in steps if step.name == "em")

    assert "-ntmpi" not in em.command
    assert em.command[:4] == ["gmx_mpi", "mdrun", "-v", "-deffnm"]


def test_strict_inputs_requires_receptor_and_ligand(tmp_path: Path) -> None:
    config = default_config("strict_test")

    with pytest.raises(FileNotFoundError):
        build_pipeline(config, config_dir=tmp_path, strict_inputs=True)


def test_non_strict_inputs_allows_missing_receptor_and_ligand(tmp_path: Path) -> None:
    config = default_config("non_strict_test")

    steps = build_pipeline(config, config_dir=tmp_path, strict_inputs=False)

    project_root = tmp_path.resolve()
    assert steps[0].inputs == [
        project_root / "inputs/receptor.pdb",
        project_root / "inputs/ligante.pdb",
    ]


def test_pipeline_uses_config_parent_work_directory(tmp_path: Path) -> None:
    steps = build_pipeline(default_config("workdir_test"), config_dir=tmp_path)

    project_root = tmp_path.resolve()
    assert steps[0].workdir == project_root / "work" / "prep"
    assert steps[-1].workdir == project_root / "outputs"


def test_analysis_step_uses_explicit_config_path(tmp_path: Path) -> None:
    config_path = tmp_path / "custom.toml"

    steps = build_pipeline(
        default_config("custom_config_test"),
        config_dir=tmp_path,
        config_path=config_path,
    )
    analysis = next(step for step in steps if step.name == "analysis")

    assert analysis.command == ["gmxflow", "analyze", "--config", str(config_path.resolve())]
    assert analysis.inputs == [
        tmp_path.resolve() / "work" / "prod" / "md.tpr",
        tmp_path.resolve() / "work" / "prod" / "md_fit.xtc",
    ]
    assert analysis.outputs == [
        tmp_path.resolve() / "work" / "analysis" / "lig.ndx",
        tmp_path.resolve() / "work" / "analysis" / "rmsd_backbone.xvg",
        tmp_path.resolve() / "work" / "analysis" / "rmsd_ligante.xvg",
        tmp_path.resolve() / "work" / "analysis" / "rmsf_residuos.xvg",
        tmp_path.resolve() / "work" / "analysis" / "gyrate.xvg",
        tmp_path.resolve() / "work" / "analysis" / "mindist.xvg",
        tmp_path.resolve() / "work" / "analysis" / "numcont.xvg",
        tmp_path.resolve() / "work" / "analysis" / "hbond.xvg",
        tmp_path.resolve() / "work" / "analysis" / "hbond.ndx",
    ]


def test_plots_step_uses_analysis_outputs(tmp_path: Path) -> None:
    config_path = tmp_path / "custom.toml"

    steps = build_pipeline(
        default_config("plots_test"),
        config_dir=tmp_path,
        config_path=config_path,
    )
    plots = next(step for step in steps if step.name == "plots")

    assert plots.name == "plots"
    assert plots.command == ["gmxflow", "plot-analysis", "--config", str(config_path.resolve())]
    assert plots.inputs == [
        tmp_path.resolve() / "work" / "analysis" / "rmsd_backbone.xvg",
        tmp_path.resolve() / "work" / "analysis" / "rmsd_ligante.xvg",
        tmp_path.resolve() / "work" / "analysis" / "rmsf_residuos.xvg",
        tmp_path.resolve() / "work" / "analysis" / "gyrate.xvg",
        tmp_path.resolve() / "work" / "analysis" / "numcont.xvg",
        tmp_path.resolve() / "work" / "analysis" / "hbond.xvg",
    ]
    assert plots.outputs == [
        tmp_path.resolve() / "work" / "analysis" / "painel_completo.png",
        tmp_path.resolve() / "work" / "analysis" / "rmsd_bb.png",
        tmp_path.resolve() / "work" / "analysis" / "rmsd_lig.png",
        tmp_path.resolve() / "work" / "analysis" / "rmsf.png",
        tmp_path.resolve() / "work" / "analysis" / "rg.png",
        tmp_path.resolve() / "work" / "analysis" / "ncont.png",
        tmp_path.resolve() / "work" / "analysis" / "hbond.png",
    ]


def test_report_step_uses_analysis_outputs_and_plots(tmp_path: Path) -> None:
    config_path = tmp_path / "custom.toml"

    steps = build_pipeline(
        default_config("report_test"),
        config_dir=tmp_path,
        config_path=config_path,
    )
    report = steps[-1]

    assert report.name == "report"
    assert report.command == ["gmxflow", "report", "--config", str(config_path.resolve())]
    assert report.workdir == tmp_path.resolve() / "outputs"
    assert report.inputs == [
        tmp_path.resolve() / "work" / "analysis" / "rmsd_backbone.xvg",
        tmp_path.resolve() / "work" / "analysis" / "rmsd_ligante.xvg",
        tmp_path.resolve() / "work" / "analysis" / "rmsf_residuos.xvg",
        tmp_path.resolve() / "work" / "analysis" / "gyrate.xvg",
        tmp_path.resolve() / "work" / "analysis" / "mindist.xvg",
        tmp_path.resolve() / "work" / "analysis" / "numcont.xvg",
        tmp_path.resolve() / "work" / "analysis" / "hbond.xvg",
        tmp_path.resolve() / "work" / "analysis" / "painel_completo.png",
        tmp_path.resolve() / "work" / "analysis" / "rmsd_bb.png",
        tmp_path.resolve() / "work" / "analysis" / "rmsd_lig.png",
        tmp_path.resolve() / "work" / "analysis" / "rmsf.png",
        tmp_path.resolve() / "work" / "analysis" / "rg.png",
        tmp_path.resolve() / "work" / "analysis" / "ncont.png",
        tmp_path.resolve() / "work" / "analysis" / "hbond.png",
    ]
    assert report.outputs == [
        tmp_path.resolve() / "outputs" / "summary.json",
        tmp_path.resolve() / "outputs" / "summary.txt",
        tmp_path.resolve() / "outputs" / "report.html",
    ]


def test_pipeline_adds_interaction_energy_when_enabled(tmp_path: Path) -> None:
    config_path = tmp_path / "custom.toml"
    config = default_config("interaction_energy_test")
    config.analysis.interaction_energy = True

    steps = build_pipeline(config, config_dir=tmp_path, config_path=config_path)
    names = [step.name for step in steps]
    interaction = next(step for step in steps if step.name == "interaction-energy")
    report = steps[-1]

    assert names[names.index("analysis") + 1] == "interaction-energy"
    assert interaction.command == [
        "gmxflow",
        "interaction-energy",
        "--config",
        str(config_path.resolve()),
    ]
    assert interaction.inputs == [
        tmp_path.resolve() / "work" / "analysis" / "rerun.mdp",
        tmp_path.resolve() / "work" / "analysis" / "lig.ndx",
        tmp_path.resolve() / "work" / "prod" / "md.gro",
        tmp_path.resolve() / "work" / "prod" / "md_fit.xtc",
        tmp_path.resolve() / "work" / "topo" / "topol.top",
    ]
    assert interaction.outputs == [
        tmp_path.resolve() / "work" / "analysis" / "interaction.tpr",
        tmp_path.resolve() / "work" / "analysis" / "interaction.edr",
        tmp_path.resolve() / "work" / "analysis" / "interaction.log",
        tmp_path.resolve() / "work" / "analysis" / "interaction_energy.xvg",
    ]
    assert tmp_path.resolve() / "work" / "analysis" / "interaction_energy.xvg" in report.inputs


def test_pipeline_adds_sasa_when_enabled(tmp_path: Path) -> None:
    config_path = tmp_path / "custom.toml"
    config = default_config("sasa_test")
    config.analysis.sasa = True

    steps = build_pipeline(config, config_dir=tmp_path, config_path=config_path)
    names = [step.name for step in steps]
    sasa = next(step for step in steps if step.name == "sasa")
    report = steps[-1]

    assert names[names.index("analysis") + 1] == "sasa"
    assert sasa.command == ["gmxflow", "sasa", "--config", str(config_path.resolve())]
    assert sasa.inputs == [
        tmp_path.resolve() / "work" / "analysis" / "lig.ndx",
        tmp_path.resolve() / "work" / "prod" / "md.tpr",
        tmp_path.resolve() / "work" / "prod" / "md_fit.xtc",
    ]
    assert sasa.outputs == [
        tmp_path.resolve() / "work" / "analysis" / "sasa_receptor.xvg",
        tmp_path.resolve() / "work" / "analysis" / "sasa_ligante.xvg",
        tmp_path.resolve() / "work" / "analysis" / "sasa_complexo.xvg",
        tmp_path.resolve() / "work" / "analysis" / "bsa.xvg",
    ]
    assert tmp_path.resolve() / "work" / "analysis" / "bsa.xvg" in report.inputs


def test_pipeline_adds_catalytic_outputs_when_configured(tmp_path: Path) -> None:
    config_path = tmp_path / "custom.toml"
    config = default_config("catalytic_test")
    config.analysis.catalytic_residues = "57,102,195"

    steps = build_pipeline(config, config_dir=tmp_path, config_path=config_path)
    analysis = next(step for step in steps if step.name == "analysis")
    plots = next(step for step in steps if step.name == "plots")
    report = steps[-1]

    assert tmp_path.resolve() / "work" / "analysis" / "catalytic_distance.xvg" in analysis.outputs
    assert tmp_path.resolve() / "work" / "analysis" / "catalytic_occupancy.xvg" in analysis.outputs
    assert tmp_path.resolve() / "work" / "analysis" / "catalytic_distance.xvg" in plots.inputs
    assert tmp_path.resolve() / "work" / "analysis" / "catalytic_occupancy.xvg" in plots.inputs
    assert tmp_path.resolve() / "work" / "analysis" / "catalytic_distance.png" in plots.outputs
    assert tmp_path.resolve() / "work" / "analysis" / "catalytic_occupancy.png" in plots.outputs
    assert tmp_path.resolve() / "work" / "analysis" / "catalytic_distance.png" in report.inputs
    assert tmp_path.resolve() / "work" / "analysis" / "catalytic_occupancy.png" in report.inputs


def test_pipeline_adds_sasa_plot_outputs_when_enabled(tmp_path: Path) -> None:
    config_path = tmp_path / "custom.toml"
    config = default_config("sasa_plots_test")
    config.analysis.sasa = True

    steps = build_pipeline(config, config_dir=tmp_path, config_path=config_path)
    plots = next(step for step in steps if step.name == "plots")
    report = steps[-1]

    assert tmp_path.resolve() / "work" / "analysis" / "sasa_complexo.xvg" in plots.inputs
    assert tmp_path.resolve() / "work" / "analysis" / "sasa_ligante.xvg" in plots.inputs
    assert tmp_path.resolve() / "work" / "analysis" / "bsa.xvg" in plots.inputs
    assert tmp_path.resolve() / "work" / "analysis" / "sasa_complexo.png" in plots.outputs
    assert tmp_path.resolve() / "work" / "analysis" / "sasa_ligante.png" in plots.outputs
    assert tmp_path.resolve() / "work" / "analysis" / "bsa.png" in plots.outputs
    assert tmp_path.resolve() / "work" / "analysis" / "sasa_complexo.png" in report.inputs
    assert tmp_path.resolve() / "work" / "analysis" / "sasa_ligante.png" in report.inputs
    assert tmp_path.resolve() / "work" / "analysis" / "bsa.png" in report.inputs


def test_select_steps_until_prepare(tmp_path: Path) -> None:
    steps = build_pipeline(default_config("select_test"), config_dir=tmp_path)

    selected = select_steps(steps, until="prepare")

    assert [step.name for step in selected] == ["prepare"]


def test_select_steps_from_until(tmp_path: Path) -> None:
    steps = build_pipeline(default_config("select_range_test"), config_dir=tmp_path)

    selected = select_steps(steps, from_step="box", until="ions")

    assert [step.name for step in selected] == ["box", "solvate", "ions-grompp", "ions"]


def test_select_steps_rejects_unknown_step(tmp_path: Path) -> None:
    steps = build_pipeline(default_config("select_error_test"), config_dir=tmp_path)

    with pytest.raises(ValueError, match="Etapa desconhecida"):
        select_steps(steps, until="missing")
