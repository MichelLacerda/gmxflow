from gmxflow.topology import reset_molecules_lines


def test_reset_molecules_lines_removes_transient_molecules_and_appends_requested() -> None:
    lines = [
        "[ system ]",
        "Protein in water",
        "",
        "[ molecules ]",
        "; Compound        #mols",
        "Protein_chain_A     1",
        "BEN                  1",
        "SOL               8700",
        "NA                  28",
        "CL                  34",
    ]

    result = reset_molecules_lines(
        lines,
        remove_molecules={"BEN", "SOL", "NA", "CL"},
        append_molecules=[("BEN", 1)],
    )

    assert "Protein_chain_A     1" in result
    assert "BEN                  1" in result
    assert "SOL               8700" not in result
    assert "NA                  28" not in result
    assert "CL                  34" not in result
