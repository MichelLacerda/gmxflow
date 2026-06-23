# Smoke Peptide Complex

Exemplo mínimo para validar o executor, os logs e o encadeamento da pipeline.

Este exemplo usa dois peptídeos curtos compostos apenas por glicina:

- `inputs/receptor.pdb`: receptor sintético com 3 resíduos GLY.
- `inputs/ligante.pdb`: ligante sintético com 2 resíduos GLY.

O arquivo `config.toml` usa:

```toml
[simulation]
profile = "smoke"
```

Esse perfil força NVT, NPT e produção a usarem apenas 10 passos. O objetivo é testar a ferramenta rapidamente. Os resultados não devem ser interpretados como dinâmica molecular científica.

Comandos úteis:

```sh
uv run gmxflow validate --config examples/smoke_peptide_complex/config.toml
uv run gmxflow run --config examples/smoke_peptide_complex/config.toml --dry-run --strict-inputs
uv run gmxflow prepare-complex --config examples/smoke_peptide_complex/config.toml --force
```
