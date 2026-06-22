from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from gmxflow.pipeline import PipelineStep


def print_dry_run(steps: list[PipelineStep], console: Console) -> None:
    console.print(Panel.fit("DRY-RUN: nenhum comando externo será executado"))

    for index, step in enumerate(steps, start=1):
        table = Table(title=f"{index}. {step.name}")
        table.add_column("Campo")
        table.add_column("Valor", overflow="fold")
        table.add_row("Descrição", step.description)
        table.add_row("Workdir", str(step.workdir))
        table.add_row("Comando", format_command(step.command))
        if step.stdin is not None:
            table.add_row("stdin", repr(step.stdin))
        table.add_row("Entradas", "\n".join(str(path) for path in step.inputs) or "-")
        table.add_row("Saídas", "\n".join(str(path) for path in step.outputs) or "-")
        console.print(table)


def format_command(command: list[str]) -> str:
    return " ".join(_quote_arg(arg) for arg in command)


def _quote_arg(arg: str) -> str:
    if not arg:
        return '""'
    if any(char.isspace() for char in arg):
        return f'"{arg}"'
    return arg
