# Lisozima em água

Este exemplo configura uma simulação proteína-em-água sem ligante, a partir da
estrutura 1AKI do [RCSB PDB](https://www.rcsb.org/structure/1AKI), seguindo como
referência de fluxo o [tutorial Lysozyme in Water do
MDTutorials](http://www.mdtutorials.com/gmx/lysozyme/index.html).

## Abrir no Jupyter

Abra `project.ipynb` usando o kernel Conda/Micromamba onde gmxflow, GROMACS e
MDAnalysis estejam disponíveis. O notebook oferece três passos: abrir o projeto,
verificar pré-requisitos e executar a pipeline. A execução pode consumir tempo
e recursos; não rode a terceira célula antes de revisar os parâmetros.

## Estrutura e preparação

O arquivo `project.toml` usa `inputs/1AKI.pdb`, declara `ligand_kind = "none"`
e solicita remover resíduos `HOH`. O gmxflow escreve a estrutura filtrada em
`work/prep/receptor_filtered.pdb`; o arquivo original é mantido intacto. A
reescrita pelo MDAnalysis não é uma cópia byte a byte do PDB. Outros nomes de
resíduo não são removidos.

Se a remoção estiver configurada e MDAnalysis estiver ausente, a validação
explica como instalar `mdanalysis` no ambiente Conda/Micromamba do kernel ou o
extra `gmxflow[notebook]` em uma instalação pip.

## Revisão científica

Os valores em `project.toml` são um ponto de partida explícito, não uma
reprodução validada do tutorial. Revise o campo de força, modelo de água, pH,
caixa, concentração de sal, protonação, tratamento de termini e parâmetros de
simulação antes de uma execução interpretável. O perfil `standard` está
configurado para 100 ns de produção. A escolha automática de protonação e
preparação estrutural não substitui revisão científica.

Para conferir arquivos e plano sem iniciar GROMACS, use no diretório deste
projeto:

```bash
gmxflow run --project project.toml --dry-run --strict-inputs
```

As análises automáticas deste modo limitam-se a RMSD do backbone, RMSF e raio de
giro. Métricas receptor-ligante não se aplicam.
