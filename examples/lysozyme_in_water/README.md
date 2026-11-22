# Lisozima em água

Este exemplo configura uma simulação proteína-em-água sem ligante, a partir da
estrutura 1AKI do [RCSB PDB](https://www.rcsb.org/structure/1AKI), seguindo como
referência de fluxo o [tutorial Lysozyme in Water do
MDTutorials](http://www.mdtutorials.com/gmx/lysozyme/index.html).

## Abrir no Jupyter

Abra `project.ipynb` usando o kernel Conda/Micromamba onde gmxflow, GROMACS e
MDAnalysis estejam disponíveis. No notebook, abra e edite o projeto, verifique
os pré-requisitos, execute a pipeline e consulte o relatório. A execução pode
consumir tempo e recursos; revise os parâmetros antes de iniciar.

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

### Diferenças de protocolo em relação ao tutorial

A comparação abaixo usa a versão do tutorial de Lemkul atualmente publicada
junto ao material LiveCoMS. O tutorial também recomenda revisar as escolhas de
modelo e protocolo conforme o sistema e a pergunta científica; esta tabela é
uma comparação descritiva, não uma recomendação de parâmetros.

| Escolha | Tutorial de referência | Este projeto (`project.toml`) |
| --- | --- | --- |
| Campo de força | CHARMM36m, pacote `charmm36-feb2026_cgenff-5.0` | Mesmo pacote configurado |
| Água | SPC/E | TIP3P; `spc216.gro` fornece coordenadas iniciais, não muda o modelo da topologia |
| Caixa | Cúbica, distância mínima 1,0 nm | Cúbica, 1,2 nm |
| Íons | Neutralização da carga líquida | Neutralização e concentração adicional de 0,15 M |
| Temperatura alvo | 298 K | 300 K |
| NVT / NPT | 100 ps cada | 100 ps cada no perfil `standard` |
| Termostato | V-rescale, grupo `System`, `tau_t = 1,0 ps` | V-rescale, grupos `Protein` e `Non-Protein`, `tau_t = 0,1 ps` |
| Barostato | C-rescale, `tau_p = 5,0 ps` | C-rescale, `tau_p = 2,0 ps` |
| Produção | 10 ns | 100 ns no perfil `standard` |

O `project.toml` está atualmente em perfil `smoke`: NVT, NPT e produção têm
somente 10 passos cada (0,02 ps por etapa, com `dt = 0,002 ps`). Isso serve
apenas para validar a integração do software; não compara os protocolos nem
produz evidência científica. Para comparar resultados, é necessário decidir e
revisar humanamente quais diferenças acima devem ser mantidas ou ajustadas, e
então executar o perfil `standard`.

Referências: [tutorial de Lysozyme in Water](http://www.mdtutorials.com/gmx/lysozyme/index.html)
e [material LiveCoMS de Justin Lemkul](https://github.com/jalemkul/gmx_tutorials_livecoms/blob/master/gmx_tutorials.tex).

Para conferir arquivos e plano sem iniciar GROMACS, use no diretório deste
projeto:

```bash
gmxflow run --project project.toml --dry-run --strict-inputs
```

As análises automáticas incluem RMSD do backbone em relação ao início da
produção, RMSD em relação à estrutura minimizada (`work/em/em.tpr`), RMSF e raio
de giro. Também são extraídos dos arquivos de energia o potencial após a
minimização, a temperatura no NVT, e a pressão e densidade no NPT. Essas séries
aparecem em figuras e no relatório junto às demais análises. A referência
minimizada segue a comparação usada no tutorial; ela não é a estrutura
cristalográfica bruta. Métricas receptor-ligante não se aplicam.

As séries termodinâmicas são lidas dos arquivos `.edr` por `gmx energy`; os
tempos são convertidos de ps para ns para manter as unidades do relatório. A
pressão instantânea em uma simulação molecular pode apresentar grandes
flutuações, portanto não deve ser interpretada isoladamente como evidência de
equilíbrio. O eixo associado à minimização representa a escala de tempo gravada
pelo GROMACS durante a minimização, não tempo físico de dinâmica molecular.
