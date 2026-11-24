from __future__ import annotations

def format_command(command: list[str]) -> str:
    return " ".join(_quote_arg(arg) for arg in command)


def _quote_arg(arg: str) -> str:
    if not arg:
        return '""'
    if any(char.isspace() for char in arg):
        return f'"{arg}"'
    return arg
