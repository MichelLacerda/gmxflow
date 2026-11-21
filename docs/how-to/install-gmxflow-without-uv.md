# Instalar O gmxflow Em Ambiente Conda/Micromamba

Este guia é para cientistas que usam Conda ou Micromamba e querem começar a usar o `gmxflow` sem precisar aprender `uv` ou detalhes de empacotamento Python.

Pense no ambiente Micromamba como o lugar único que reúne as ferramentas do trabalho: Python, GROMACS, `gmxflow` e, se desejado, Jupyter. Não é necessário criar uma instalação separada para “desenvolvimento” e outra para “produção”. Se você já tem um ambiente onde `gmx --version` funciona, pode instalar o `gmxflow` nele.

## Pré-Requisitos

- Micromamba instalado.
- Ambiente Micromamba com Python 3.12 ou mais novo.
- GROMACS instalado no mesmo ambiente e acessível como `gmx`.

Confira:

```sh
python --version
gmx --version
```

Se você precisa instalar GROMACS com CUDA/NVIDIA, veja:

- [Como instalar GROMACS com CUDA usando Micromamba](install-gromacs-cuda.md)

## Instalar No Ambiente Que Já Tem GROMACS

Ative o ambiente onde você já usa GROMACS:

```sh
micromamba activate gmx_compile
```

Se ainda não houver Python e `pip` nesse ambiente, instale-os junto com as ferramentas comuns para preparar ligantes:

```sh
micromamba install -c conda-forge python=3.12 pip git openbabel -y
```

Se o GROMACS também será instalado por Micromamba, instale-o ou compile-o nesse mesmo ambiente. Para CUDA/NVIDIA, veja:

- [Como instalar GROMACS com CUDA usando Micromamba](install-gromacs-cuda.md)

Depois instale o `gmxflow` direto do GitHub com `pip`:

`python -m pip` instala no Python do ambiente Micromamba que está ativo; não cria outro ambiente.

```sh
python -m pip install --upgrade pip
python -m pip install "git+https://github.com/MichelLacerda/gmxflow.git"
```

Verifique:

```sh
gmxflow --help
```

## Usar O `gmxflow` Em Jupyter

Instale Jupyter e as bibliotecas para exibir os relatórios no mesmo ambiente onde estão GROMACS e `gmxflow`, ative esse ambiente e inicie o notebook por ele:

```sh
micromamba install -n gmx_compile -c conda-forge jupyterlab python-lsp-server jupyterlab-lsp ipykernel ipython ipympl pandas -y
micromamba activate gmx_compile
jupyter lab
```

Assim, o kernel iniciado pelo Jupyter encontra os mesmos comandos `gmx` e `gmxflow` disponíveis no terminal. Se você já inicia Jupyter por outro ambiente, registre o kernel uma vez enquanto `gmx_compile` estiver ativo:

```sh
python -m ipykernel install --user --name gmx_compile --display-name "Python (gmx_compile)"
```

No notebook, selecione o kernel **Python (gmx_compile)**. O repositório mantém projetos prontos para abrir em [examples/smoke_peptide_complex/project.ipynb](../../examples/smoke_peptide_complex/project.ipynb) e [examples/protein_ligand_complex/project.ipynb](../../examples/protein_ligand_complex/project.ipynb). Cada pasta contém fisicamente o notebook, `project.toml` e `inputs/`; o notebook trabalha diretamente no exemplo, sem copiar arquivos em tempo de execução. Após a execução, `project.show_report()` exibe resumo, tabelas nativas do pandas e gráficos Matplotlib interativos gerados a partir dos dados da análise, com controles de navegação e salvamento; não são carregados os PNGs usados no relatório distribuível. O HTML compartilhável fica em `outputs/report.html`. O extra opcional `gmxflow[notebook]` instala IPython, ipympl e pandas quando o pacote é instalado com pip. Se instalou essas bibliotecas com o Jupyter aberto, reinicie o kernel antes de consultar o relatório. O exemplo `smoke` é apenas um teste de integração, não uma simulação cientificamente interpretável. A API usada pelos notebooks ainda é experimental. Projetos criados com `gmxflow startproject` também incluem `project.ipynb`.

Para limpar artefatos intermediários pelo próprio notebook, execute `project.clean()`. Por padrão, ele limpa `work/`, preservando os templates `.mdp`, os arquivos em `inputs/` e os resultados em `outputs/`. Use `project.clean(remove_templates=True)` para remover também os templates, ou `project.clean(all_work=True)` para descartar todo o conteúdo de `work/` e recriar suas pastas.

Atualizar:

```sh
micromamba activate gmx_compile
python -m pip install --upgrade "git+https://github.com/MichelLacerda/gmxflow.git"
```

Remover:

```sh
micromamba activate gmx_compile
python -m pip uninstall gmxflow
```

## Instalar Uma Versão Específica

Quando houver tags, prefira instalar uma versão fixa:

```sh
micromamba activate gmx_compile
python -m pip install "git+https://github.com/MichelLacerda/gmxflow.git@v0.1.0"
```

Enquanto o projeto estiver em `0.x`, a interface ainda pode mudar entre versões minor.

## Opcional: Modificar O Código Do gmxflow

Ignore esta seção se seu objetivo é apenas usar o `gmxflow` em simulações. Ela só é necessária para quem pretende editar o próprio software.

```sh
git clone https://github.com/MichelLacerda/gmxflow.git
cd gmxflow
micromamba activate gmx_compile
python -m pip install --upgrade pip
python -m pip install -e .
python -m pip install pytest ruff mypy
```

Verifique:

```sh
gmxflow --help
python -m pytest
```

## Instalação Dentro De Distrobox

Se você usa Distrobox:

```sh
distrobox enter Bioagro
micromamba activate gmx_compile
python -m pip install "git+https://github.com/MichelLacerda/gmxflow.git"
```

Se quiser exportar o comando para o host:

```sh
distrobox-export --bin "$(command -v gmxflow)"
```

## Problemas Comuns

### `gmxflow: command not found`

Confirme que o ambiente Micromamba correto está ativo:

```sh
micromamba activate gmx_compile
which python
which gmxflow
```

Se `gmxflow` não aparecer, reinstale dentro do ambiente ativo:

```sh
python -m pip install --upgrade "git+https://github.com/MichelLacerda/gmxflow.git"
```

### `gmx: command not found`

O `gmxflow` foi instalado, mas o GROMACS não está disponível.

Ative o ambiente onde o GROMACS foi instalado:

```sh
micromamba activate gmx_compile
```

ou carregue o `GMXRC`:

```sh
source "$HOME/gromacs_cuda/bin/GMXRC"
```

### Erro Ao Instalar Dependências

Atualize `pip`:

```sh
python -m pip install --upgrade pip
```

Se estiver em rede institucional, verifique proxy/firewall.

### Repositório Privado

Se o repositório ainda estiver privado, use SSH:

```sh
micromamba activate gmx_compile
python -m pip install "git+ssh://git@github.com/MichelLacerda/gmxflow.git"
```

Quando o repositório estiver público, a URL HTTPS deve funcionar para qualquer usuário.
