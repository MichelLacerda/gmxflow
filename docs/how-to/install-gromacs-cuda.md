# Como Instalar GROMACS Com CUDA Usando Micromamba

Este guia documenta a instalação do GROMACS com suporte a CUDA a partir do código-fonte, em uma pasta do usuário, usando `micromamba` para fornecer compiladores, CMake e CUDA Toolkit.

Ele foi escrito a partir de um caso real com GPU NVIDIA RTX 5070 Ti, arquitetura Blackwell, em que builds prontas falhavam com erros como:

```text
cudaErrorNoKernelImageForDevice
cudaErrorUnsupportedPtxVersion
cudaErrorInvalidPtx
```

Referências oficiais:

- GROMACS installation guide: <https://manual.gromacs.org/current/install-guide/index.html>
- Seção CUDA GPU acceleration: <https://manual.gromacs.org/current/install-guide/index.html#cuda-gpu-acceleration>

Segundo a documentação do GROMACS 2026.2, CUDA é o backend recomendado para GPUs NVIDIA, o CUDA Toolkit precisa ser 12.1 ou mais novo, e o `GMXRC` deve ser carregado após a instalação para expor o comando `gmx`.

## Quando Usar Este Guia

Use este guia quando:

- você tem GPU NVIDIA recente;
- `gmx --version` não mostra `GPU support: CUDA`;
- builds prontas do Conda/Micromamba não funcionam bem na sua GPU;
- você não quer ou não pode instalar GROMACS globalmente com `sudo`;
- você está usando Distrobox ou ambiente de usuário isolado.

Em Distrobox, confirme antes que a GPU está visível dentro do container:

```sh
nvidia-smi
```

Se `nvidia-smi` não funcionar dentro do Distrobox, resolva isso primeiro no host/container. Compilar o GROMACS não corrige ausência de driver NVIDIA visível.

## Pré-Requisitos

- Driver NVIDIA instalado no host.
- `nvidia-smi` funcionando no ambiente onde você vai rodar o GROMACS.
- `micromamba` instalado e inicializado.
- Espaço em disco para compilar GROMACS.
- Acesso à internet para baixar código-fonte e dependências.

## Instalação Do Zero

### 1. Remover Tentativas Antigas

Opcional, mas recomendado se você já tentou instalar antes:

```sh
micromamba env remove -n gmx_compile -y
rm -rf "$HOME/gromacs_cuda"
rm -rf "$HOME/gromacs-2026.2"
rm -f "$HOME/gromacs-2026.2.tar.gz"
```

### 2. Criar Ambiente De Compilação

```sh
micromamba create -n gmx_compile -c conda-forge \
  python=3.12 \
  openbabel \
  gxx_linux-64 \
  sysroot_linux-64=2.17 \
  cmake \
  cuda-nvcc \
  cuda-toolkit \
  wget \
  make \
  -y
```

Ative:

```sh
micromamba activate gmx_compile
```

Garanta que os binários e bibliotecas do ambiente vêm primeiro:

```sh
export PATH="$CONDA_PREFIX/bin:$PATH"
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:${LD_LIBRARY_PATH:-}"
```

Confira:

```sh
which nvcc
nvcc --version
cmake --version
nvidia-smi
```

### 3. Baixar GROMACS

```sh
cd "$HOME"
wget https://ftp.gromacs.org/gromacs/gromacs-2026.2.tar.gz
tar xfz gromacs-2026.2.tar.gz
cd gromacs-2026.2
mkdir build
cd build
```

### 4. Configurar CMake Com CUDA

Para GPUs novas, especialmente Blackwell/RTX 50xx, use:

```sh
cmake .. \
  -DGMX_GPU=CUDA \
  -DCMAKE_CUDA_ARCHITECTURES="all" \
  -DCMAKE_CUDA_COMPILER="$CONDA_PREFIX/bin/nvcc" \
  -DCMAKE_PREFIX_PATH="$CONDA_PREFIX" \
  -DCMAKE_INSTALL_PREFIX="$HOME/gromacs_cuda" \
  -DGMX_BUILD_OWN_FFTW=ON \
  -DREGRESSIONTEST_DOWNLOAD=ON \
  -DCMAKE_BUILD_TYPE=Release
```

Notas:

- `-DGMX_GPU=CUDA` ativa o backend CUDA.
- `-DCMAKE_CUDA_COMPILER="$CONDA_PREFIX/bin/nvcc"` força o uso do `nvcc` do ambiente.
- `-DCMAKE_PREFIX_PATH="$CONDA_PREFIX"` ajuda o CMake a encontrar CUDA/cuFFT e bibliotecas do micromamba.
- `-DCMAKE_CUDA_ARCHITECTURES="all"` evita prender a build em arquiteturas antigas quando a GPU é muito nova.
- `-DCMAKE_INSTALL_PREFIX="$HOME/gromacs_cuda"` instala sem `sudo`.

### 5. Compilar E Instalar

Use um número de jobs compatível com sua CPU:

```sh
make -j 16
make install
```

Se quiser rodar testes de regressão:

```sh
make check
```

Em máquinas pessoais, `make check` pode demorar. Para instalação de desenvolvimento local, compilar e validar com `gmx --version` e um exemplo `smoke` do `gmxflow` costuma ser suficiente.

### 6. Carregar GROMACS

Na sessão atual:

```sh
source "$HOME/gromacs_cuda/bin/GMXRC"
```

Verifique:

```sh
which gmx
gmx --version
```

Procure:

```text
GPU support: CUDA
```

## Ativação Automática Com Micromamba

Para carregar o GROMACS sempre que ativar `gmx_compile`:

```sh
mkdir -p "$CONDA_PREFIX/etc/conda/activate.d"
mkdir -p "$CONDA_PREFIX/etc/conda/deactivate.d"

printf 'source "$HOME/gromacs_cuda/bin/GMXRC"\n' \
  > "$CONDA_PREFIX/etc/conda/activate.d/gromacs.sh"

cat > "$CONDA_PREFIX/etc/conda/deactivate.d/gromacs.sh" <<'EOF'
unset GMXDATA
unset GMXBIN
unset GMXLDLIB
EOF
```

Depois, em um novo terminal:

```sh
micromamba activate gmx_compile
which gmx
gmx --version
```

## Usar Com O `gmxflow`

Ative o ambiente antes de rodar:

```sh
micromamba activate gmx_compile
cd /caminho/para/gmxflow
gmxflow validate --config examples/protein_ligand_complex/config.toml
```

Para CPU:

```toml
[mdrun]
gpu = "off"
```

Para forçar GPU:

```toml
[mdrun]
gpu = "force"
gpu_id = "0"
ntomp = 8
pin = "on"
```

O `gmxflow` usa comandos compatíveis com as limitações do GROMACS:

- minimização (`em`) não força PME/bonded na GPU;
- produção/equilíbrios usam `mdrun` com `-nb gpu` quando `gpu = "force"`;
- análise opcional de energia por rerun força `-nb cpu`, porque múltiplos energy groups não são suportados em GPU.

## Comandos Manuais De Referência

Minimização:

```sh
gmx mdrun -v -deffnm em -ntmpi 1 -ntomp 8 -nb gpu -gpu_id 0
```

NVT/NPT/produção:

```sh
gmx mdrun -v -deffnm nvt -ntmpi 1 -ntomp 8 -nb gpu -gpu_id 0 -pin on
```

## Problemas Comuns

### `cudaErrorNoKernelImageForDevice`

O binário pronto não contém código compatível com sua GPU.

Solução: compile GROMACS localmente com CUDA, usando `CMAKE_CUDA_ARCHITECTURES` adequado. Para GPUs muito novas, `all` foi a opção mais robusta no caso RTX 5070 Ti.

### `cudaErrorUnsupportedPtxVersion` Ou `cudaErrorInvalidPtx`

Há incompatibilidade entre driver, CUDA Toolkit e código gerado.

Soluções:

- atualize o driver NVIDIA no host;
- use CUDA Toolkit recente no ambiente;
- compile localmente em vez de usar build pronta;
- evite fixar arquitetura CUDA antiga, como `90`, para GPU Blackwell.

### `CUDA::cufft target was not found`

O CMake não encontrou cuFFT.

Solução: instale `cuda-toolkit` no ambiente e use:

```sh
-DCMAKE_PREFIX_PATH="$CONDA_PREFIX"
```

### `CMAKE_CUDA_COMPILER is not a full path`

O CMake recebeu um caminho inválido para `nvcc`.

Solução:

```sh
-DCMAKE_CUDA_COMPILER="$CONDA_PREFIX/bin/nvcc"
```

### PME/Bonded Na GPU Falha Na Minimização

Minimização com integrador `steep` não é dinâmica molecular real. O GROMACS não permite certos offloads para GPU nesse modo.

Solução: não force `-pme gpu` nem `-bonded gpu` na minimização. Use apenas `-nb gpu`, ou deixe o `gmxflow` montar o comando.

## Status Esperado

Ao final:

```sh
micromamba activate gmx_compile
gmx --version
```

deve mostrar:

```text
GPU support: CUDA
```

e o `gmxflow` deve conseguir usar:

```toml
[mdrun]
gpu = "force"
gpu_id = "0"
```
