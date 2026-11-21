# Smoke Peptide Complex

Esta é uma cópia física do exemplo disponibilizada para uso no Jupyter. Abra
[`project.ipynb`](./project.ipynb); `examples/smoke_peptide_complex` é a cópia de
referência mantida na raiz do repositório.

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
uv run gmxflow validate --config config.toml
uv run gmxflow run --config config.toml --dry-run --strict-inputs
uv run gmxflow prepare-complex --config config.toml --force
```

O teste automatizado ponta a ponta da API exige GROMACS e o force field
`amber99sb-ildn` disponíveis no ambiente ativo. Ele copia este exemplo para um
diretório temporário, executa a pipeline duas vezes para verificar retomada e
logs, e não altera os arquivos versionados. Para executá-lo:

```sh
uv run pytest -m gromacs ../../tests/integration/test_api_gromacs.py
```

Os testes unitários comuns excluem essa integração por padrão. O teste continua
sendo apenas uma verificação de integração do software; não produz resultados
cientificamente interpretáveis.
