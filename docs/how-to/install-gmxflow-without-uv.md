# Como Instalar O gmxflow Sem Usar uv

Este guia é para usuários finais que querem usar o comando `gmxflow`, mas não querem instalar nem aprender `uv`.

Para desenvolvimento do projeto, `uv` continua sendo recomendado. Para uso normal dentro de um ambiente científico, use `micromamba` e instale o `gmxflow` com `pip` dentro desse ambiente.

## Pré-Requisitos

- Micromamba instalado.
- Ambiente Micromamba com Python 3.12 ou mais novo.
- GROMACS instalado no mesmo ambiente e acessível como `gmx`.
- Git instalado.

Confira:

```sh
python --version
git --version
gmx --version
```

Se você precisa instalar GROMACS com CUDA/NVIDIA, veja:

- [Como instalar GROMACS com CUDA usando Micromamba](install-gromacs-cuda.md)

## Opção Recomendada: Ambiente Micromamba

Ative o ambiente onde você já usa GROMACS:

```sh
micromamba activate gmx_compile
```

Instale dependências úteis no mesmo ambiente, se ainda não existirem:

```sh
micromamba install -c conda-forge python=3.12 pip git openbabel -y
```

Se o GROMACS também será instalado por Micromamba, instale-o ou compile-o nesse mesmo ambiente. Para CUDA/NVIDIA, veja:

- [Como instalar GROMACS com CUDA usando Micromamba](install-gromacs-cuda.md)

Depois instale o `gmxflow` direto do GitHub com `pip`:

```sh
python -m pip install --upgrade pip
python -m pip install "git+https://github.com/MichelLacerda/gmxflow.git"
```

Verifique:

```sh
gmxflow --help
```

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

## Instalação Editável Para Testar Mudanças Locais

Use esta opção se você clonou o repositório e quer modificar o código.

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
