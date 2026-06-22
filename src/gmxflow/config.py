from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, Field, PositiveFloat, PositiveInt


class ProjectConfig(BaseModel):
    name: str = "dm_complex"
    description: str = "Simulação de dinâmica molecular com GROMACS"


class InputConfig(BaseModel):
    receptor_pdb: str = "inputs/receptor.pdb"
    ligand_pdb: str = "inputs/ligante.pdb"
    ligand_kind: str = "peptide"
    ligand_mol2: str = ""
    ligand_str: str = ""
    ligand_resname: str = "LIG"
    ph: float = Field(default=7.4, ge=0, le=14)


class ForceFieldConfig(BaseModel):
    name: str = "amber99sb-ildn"
    water: str = "tip3p"


class BoxConfig(BaseModel):
    type: str = "dodecahedron"
    distance_nm: PositiveFloat = 1.2


class SolventConfig(BaseModel):
    water_structure: str = "spc216.gro"
    salt_concentration_m: float = Field(default=0.15, ge=0)
    positive_ion: str = "NA"
    negative_ion: str = "CL"
    neutralize: bool = True


class SimulationConfig(BaseModel):
    profile: str = "standard"
    temperature_k: PositiveFloat = 300
    pressure_bar: PositiveFloat = 1.0
    dt_ps: PositiveFloat = 0.002
    production_ns: PositiveInt = 100
    nvt_ps: PositiveFloat = 100
    npt_ps: PositiveFloat = 100

    @property
    def production_steps(self) -> int:
        if self.profile == "smoke":
            return 10
        return int((self.production_ns * 1000) / self.dt_ps)

    @property
    def nvt_steps(self) -> int:
        if self.profile == "smoke":
            return 10
        return int(self.nvt_ps / self.dt_ps)

    @property
    def npt_steps(self) -> int:
        if self.profile == "smoke":
            return 10
        return int(self.npt_ps / self.dt_ps)


class MdrunConfig(BaseModel):
    engine: str = "auto"
    gpu: str = "auto"
    gpu_id: str = "0"
    ntomp: PositiveInt = 8
    pin: str = "auto"


class AnalysisConfig(BaseModel):
    ligand_chain: str = "B"
    fit_group: str = "Backbone"
    center_group: str = "Protein"
    output_group: str = "System"
    contact_cutoff_nm: PositiveFloat = 0.4
    interaction_energy: bool = False
    sasa: bool = False
    catalytic_residues: str = ""
    catalytic_distance_cutoff_nm: PositiveFloat = 0.4


class PlotsConfig(BaseModel):
    receptor_color: str = "#1f77b4"
    ligand_color: str = "#C2185B"
    band_window: PositiveInt = 25
    band_std: PositiveFloat = 2.0
    raw_alpha: float = Field(default=0.18, ge=0, le=1)
    band_alpha: float = Field(default=0.22, ge=0, le=1)


class GmxFlowConfig(BaseModel):
    project: ProjectConfig = Field(default_factory=ProjectConfig)
    input: InputConfig = Field(default_factory=InputConfig)
    force_field: ForceFieldConfig = Field(default_factory=ForceFieldConfig)
    box: BoxConfig = Field(default_factory=BoxConfig)
    solvent: SolventConfig = Field(default_factory=SolventConfig)
    simulation: SimulationConfig = Field(default_factory=SimulationConfig)
    mdrun: MdrunConfig = Field(default_factory=MdrunConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    plots: PlotsConfig = Field(default_factory=PlotsConfig)


def load_config(path: Path) -> GmxFlowConfig:
    with path.open("rb") as file:
        data = tomllib.load(file)
    return GmxFlowConfig.model_validate(data)


def default_config(project_name: str) -> GmxFlowConfig:
    return GmxFlowConfig(
        project=ProjectConfig(
            name=project_name,
        )
    )


def to_toml(config: GmxFlowConfig) -> str:
    data = config.model_dump()
    lines: list[str] = []
    for section, values in data.items():
        lines.append(f"[{section}]")
        for key, value in values.items():
            lines.append(f"{key} = {_toml_value(value)}")
        lines.append("")
        if section == "project":
            lines.extend(_commented_paths_block())
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return f'"{value}"'


def _commented_paths_block() -> list[str]:
    return [
        "# [paths]",
        "# Uso avançado: por padrão, o gmxflow usa a pasta onde está o config.toml",
        "# como raiz do projeto. Os arquivos intermediários ficam em ./work e os",
        "# resultados finais ficam em ./outputs. Futuramente estes campos poderão",
        "# redirecionar dados pesados para outro disco, SSD externo ou scratch de HPC.",
        '# work_dir = "work"',
        '# output_dir = "outputs"',
    ]
