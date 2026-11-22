"""Interactive project configuration form for Jupyter notebooks."""

from __future__ import annotations

import html
import os
import stat
import tempfile
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from gmxflow.config import GmxFlowConfig

if TYPE_CHECKING:
    from gmxflow.api import GmxFlowProject


_SECTIONS: tuple[tuple[str, str, str], ...] = (
    ("project", "Projeto", "Nome e descrição do projeto."),
    (
        "input",
        "Estrutura e sistema molecular",
        "Informe os arquivos de entrada e o tipo de sistema. Caminhos relativos são resolvidos a partir da pasta do projeto.",
    ),
    ("force_field", "Campo de força", "Defina o campo de força e o modelo de água."),
    ("box", "Caixa de simulação", "Parâmetros geométricos da caixa."),
    ("solvent", "Solvente e íons", "Composição do solvente e concentração de sal."),
    ("simulation", "Parâmetros de simulação", "Temperatura, pressão e duração das etapas."),
    ("mdrun", "Recursos de execução", "Preferências de CPU e GPU para o GROMACS."),
    ("pdb2gmx", "Termini da proteína", "Seleções de terminais encaminhadas ao pdb2gmx."),
    ("analysis", "Análises", "Grupos e análises selecionados para o sistema."),
    ("plots", "Gráficos", "Ajustes visuais das figuras geradas."),
)

_LABELS = {
    "project.name": "Nome",
    "project.description": "Descrição",
    "input.receptor_pdb": "Arquivo PDB do receptor",
    "input.ligand_pdb": "Arquivo PDB do ligante",
    "input.ligand_kind": "Tipo de sistema",
    "input.remove_resnames": "Resíduos a remover (separados por vírgula)",
    "input.ligand_mol2": "Arquivo MOL2 do ligante",
    "input.ligand_str": "Arquivo STR do CGenFF",
    "input.ligand_resname": "Nome do resíduo do ligante",
    "input.ph": "pH usado na preparação",
    "force_field.name": "Campo de força",
    "force_field.water": "Modelo de água",
    "box.distance_nm": "Distância até a borda (nm)",
    "solvent.salt_concentration_m": "Concentração de sal (mol/L)",
    "simulation.profile": "Perfil",
    "simulation.temperature_k": "Temperatura (K)",
    "simulation.pressure_bar": "Pressão (bar)",
    "simulation.dt_ps": "Passo de integração (ps)",
    "simulation.production_ns": "Produção (ns)",
    "simulation.nvt_ps": "Equilíbrio NVT (ps)",
    "simulation.npt_ps": "Equilíbrio NPT (ps)",
    "mdrun.engine": "Executável GROMACS",
    "mdrun.gpu": "Uso de GPU",
    "mdrun.gpu_id": "Identificador da GPU",
    "mdrun.ntomp": "Threads OpenMP",
    "mdrun.pin": "Afinidade de CPU",
    "analysis.contact_cutoff_nm": "Distância de contato (nm)",
    "analysis.catalytic_distance_cutoff_nm": "Distância catalítica (nm)",
    "plots.band_window": "Janela de suavização",
    "plots.band_std": "Desvio da banda",
}

_OPTIONS: dict[str, tuple[tuple[str, str], ...]] = {
    "input.ligand_kind": (
        ("Peptídeo", "peptide"),
        ("Molécula pequena parametrizada (CGenFF)", "small_molecule"),
        ("Sem ligante (proteína em água)", "none"),
    ),
    "simulation.profile": (
        ("Padrão (simulação configurada)", "standard"),
        ("Smoke (teste de integração; sem interpretação científica)", "smoke"),
    ),
    "mdrun.engine": (("Automático", "auto"), ("GROMACS", "gmx"), ("GROMACS MPI", "gmx_mpi")),
    "mdrun.gpu": (("Automático", "auto"), ("Desativada", "off"), ("Obrigatória", "force")),
}


def edit_project_config(project: GmxFlowProject) -> Any:
    """Display a validated form that updates the project's TOML on request."""
    try:
        widgets = import_module("ipywidgets")
        tomlkit = import_module("tomlkit")
    except ImportError as error:
        raise RuntimeError(
            "O formulário de configuração requer ipywidgets e tomlkit. "
            "Instale `gmxflow[notebook]` no ambiente do kernel e reinicie-o."
        ) from error

    original_text = project.config_path.read_bytes()
    controls: dict[str, Any] = {}
    accordion_children = []
    section_names = []
    config_data = project.config.model_dump(mode="python")

    for section, title, description in _SECTIONS:
        section_config = getattr(project.config, section)
        rows = [widgets.HTML(value=f"<p>{html.escape(description)}</p>")]
        for field_name, value in section_config.model_dump().items():
            key = f"{section}.{field_name}"
            control = _make_control(widgets, key, value)
            controls[key] = control
            rows.append(widgets.HBox([control]))
        accordion_children.append(widgets.VBox(rows))
        section_names.append(title)

    accordion = widgets.Accordion(children=accordion_children)
    for index, title in enumerate(section_names):
        accordion.set_title(index, title)
    accordion.selected_index = 0

    notice = widgets.HTML(
        value=(
            "<p><b>Revise antes de salvar:</b> a validação confere os tipos e limites "
            "configurados, mas não avalia se as escolhas são cientificamente apropriadas. "
            "O perfil smoke serve apenas para testar a integração do software.</p>"
        )
    )
    save_button = widgets.Button(description="Validar e salvar project.toml", button_style="success")
    output = widgets.Output()

    def save(_: Any) -> None:
        nonlocal original_text
        with output:
            output.clear_output()
            try:
                updates: dict[str, dict[str, Any]] = {}
                for dotted_key, control in controls.items():
                    section, field_name = dotted_key.split(".", maxsplit=1)
                    updates.setdefault(section, {})[field_name] = _read_control(control)

                for section, values in updates.items():
                    config_data[section].update(values)
                updated_config = GmxFlowConfig.model_validate(config_data)
                _write_config_updates(
                    project.config_path,
                    expected_content=original_text,
                    config=updated_config,
                    updates=updates,
                    tomlkit=tomlkit,
                )
                project.config = updated_config
                original_text = project.config_path.read_bytes()
                display_module = import_module("IPython.display")
                display_module.display(
                    display_module.Markdown(
                        f"Configuração validada e salva em `{project.config_path}`."
                    )
                )
            except (OSError, RuntimeError, ValidationError, ValueError) as error:
                display_module = import_module("IPython.display")
                display_module.display(
                    display_module.Markdown(
                        "**A configuração não foi salva.**\n\n```text\n"
                        + html.escape(str(error))
                        + "\n```"
                    )
                )

    save_button.on_click(save)
    return widgets.VBox([notice, accordion, save_button, output])


def _make_control(widgets: Any, key: str, value: Any) -> Any:
    label = _LABELS.get(key, key.rsplit(".", maxsplit=1)[-1].replace("_", " ").capitalize())
    tooltip = label
    if key in _OPTIONS:
        return widgets.Dropdown(
            options=_OPTIONS[key],
            value=value,
            description=label,
            style={"description_width": "initial"},
            layout=widgets.Layout(width="100%"),
            tooltip=tooltip,
        )
    if isinstance(value, bool):
        return widgets.Checkbox(value=value, description=label, indent=False, tooltip=tooltip)
    if isinstance(value, int):
        return widgets.IntText(
            value=value,
            description=label,
            style={"description_width": "initial"},
            layout=widgets.Layout(width="100%"),
            tooltip=tooltip,
        )
    if isinstance(value, float):
        return widgets.FloatText(
            value=value,
            description=label,
            style={"description_width": "initial"},
            layout=widgets.Layout(width="100%"),
            tooltip=tooltip,
        )
    if isinstance(value, list):
        text_value = ", ".join(str(item) for item in value)
        description = label + " (separados por vírgula)"
    else:
        text_value = str(value)
        description = label
    return widgets.Text(
        value=text_value,
        description=description,
        style={"description_width": "initial"},
        layout=widgets.Layout(width="100%"),
        tooltip=tooltip,
    )


def _read_control(control: Any) -> Any:
    value = control.value
    if isinstance(value, str) and control.description.endswith("(separados por vírgula)"):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


def _write_config_updates(
    config_path: Path,
    *,
    expected_content: bytes,
    config: GmxFlowConfig,
    updates: dict[str, dict[str, Any]],
    tomlkit: Any,
) -> None:
    current_content = config_path.read_bytes()
    if current_content != expected_content:
        raise RuntimeError(
            "project.toml foi alterado enquanto o formulário estava aberto. "
            "Reabra o formulário para evitar sobrescrever mudanças recentes."
        )

    document = tomlkit.parse(current_content.decode("utf-8"))
    normalized = config.model_dump(mode="python")
    for section, values in updates.items():
        table = document[section]
        for field_name in values:
            table[field_name] = normalized[section][field_name]

    mode = stat.S_IMODE(config_path.stat().st_mode)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=config_path.parent,
            prefix=f".{config_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(tomlkit.dumps(document))
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.chmod(temporary_path, mode)
        os.replace(temporary_path, config_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
