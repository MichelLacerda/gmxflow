# Roadmap do gmxflow

Este roadmap organiza a evolução do `gmxflow` de uma CLI para uma ferramenta mais robusta de preparação, execução e análise de pipelines de dinâmica molecular com GROMACS.

A CLI é a interface disponível hoje. A direção de produto proposta é priorizar cientistas que trabalham em ambientes Conda/Micromamba e oferecer uma API Python de domínio, simples e voltada a pessoas, usada principalmente dentro de Jupyter; a CLI permanece como interface complementar para automação e usuários avançados.

O estado atual já é adequado para desenvolvimento e para experimentos controlados de proteína + peptídeo. O fluxo proteína + ligante pequeno também está integrado para casos com parametrização externa CGenFF já disponível, mas ainda não deve ser tratado como ferramenta geral para qualquer sistema molecular.

## Estado Atual

Implementado:

- criação de projeto com `gmxflow startproject`;
- presets no `startproject` para `ligand_kind`, `simulation.profile` e `mdrun.gpu`;
- `.gitignore` gerado automaticamente para evitar commit de `work/` e `outputs/`;
- configuração TOML validada com Pydantic;
- README de projeto gerado automaticamente;
- templates `.mdp` internos com Jinja2;
- renderização de templates em `work/` com `gmxflow render-templates`;
- setup dedicado com `gmxflow setup-workspace`;
- plano resumido com `gmxflow plan`;
- dry-run detalhado com `gmxflow run --dry-run`;
- limpeza de artefatos regeneráveis com `gmxflow clean`;
- preparação interna de complexo proteína + peptídeo com `gmxflow prepare-complex`;
- execução real da pipeline GROMACS até pós-processamento e análise;
- etapas condicionais `ligand-topology`, `protein-topology` e `assemble-complex` para `ligand_kind = "small_molecule"`;
- logs por etapa em `work/logs/`;
- retomada por etapa com `--from-step` e `--until`;
- estado persistente em `work/state.json`;
- skip automático quando outputs esperados existem e fingerprints de entradas/configuração continuam válidos;
- feedback progressivo no console durante `gmxflow run`;
- pós-processamento PBC e alinhamento com `gmx trjconv`;
- análises com `gmx rms`, `gmx rmsf`, `gmx gyrate`, `gmx mindist` e `gmx hbond`;
- geração de figuras PNG a partir dos `.xvg`;
- relatório consolidado em `outputs/summary.json`, `outputs/summary.txt` e `outputs/report.html`;
- publicação de figuras, séries `.xvg` e logs em `outputs/`;
- energia de interação opcional por `gmx mdrun -rerun`;
- SASA/BSA opcional por `gmx sasa`;
- métricas opcionais de distância e ocupação contra resíduos catalíticos;
- comando `gmxflow list-residues`;
- exemplo mínimo `examples/smoke_peptide_complex`;
- fluxo experimental `small_molecule` validado em modo `smoke` com 3ATL + benzamidina;
- exemplo local/experimental `examples/ph82`;
- testes automatizados com `pytest`;
- lint com `ruff`;
- dependências gerenciadas com `uv`.

Limitações atuais:

- a CLI continua sendo a interface estável; há uma API Python experimental e notebooks iniciais por projeto, mas ainda não há fluxo Jupyter estável e completo;
- a instalação para usuários exige instalar o pacote Python manualmente e entender como iniciar Jupyter no ambiente correto;
- foco principal em receptor + ligante peptídico;
- preparação estrutural ainda simples;
- protonação de histidina por regra fixa de pH;
- sem parametrização automática de ligantes pequenos;
- `small_molecule` depende de `.mol2`, `.str` e force field CHARMM/CGenFF já obtidos externamente;
- a política de refazer etapas ainda é simples e baseada em fingerprints dos inputs rastreados, comando, stdin, env e estado declarado da etapa;
- parâmetros GROMACS importantes ainda estão parcialmente fixos nos templates `.mdp`;
- métricas opcionais de energia, SASA/BSA e resíduos catalíticos ainda precisam de validação ampla em sistemas reais;
- sem CI remoto configurado.

## Fase 1: Base Da CLI

Status: concluída para o escopo inicial.

Entregue:

- `startproject`;
- presets `--ligand-kind`, `--profile` e `--gpu`;
- `.gitignore` gerado em novos projetos;
- `validate`;
- `plan`;
- `run --dry-run`;
- templates internos;
- README gerado;
- testes e lint.

Itens que podem voltar como melhoria incremental:

- padronizar mais mensagens de erro;
- ampliar testes de PDB para casos patológicos;
- otimizar a detecção de pontes dissulfeto com distância quadrada.

## Fase 2: Executor Real Da Pipeline

Status: concluída para o escopo atual.

Entregue:

- executor em `src/gmxflow/executor.py`;
- execução via `subprocess.run` sem shell;
- captura de `stdout` e `stderr`;
- logs por etapa;
- tempo de execução por etapa;
- parada em erro com referência ao log;
- retomada com `--from-step`;
- execução parcial com `--until`;
- `work/state.json`;
- fingerprints de entradas/configuração relevantes;
- skip automático quando outputs, comando, stdin, env, estado declarado e fingerprints continuam válidos;
- feedback progressivo no console.

Pendente:

- política mais explícita para refazer etapas em casos ambíguos;
- mensagens melhores recomendando `clean`, `--from-step` ou remoção seletiva de outputs quando necessário.

## Fase 3: Workspace, Templates e Parâmetros GROMACS

Status: parcialmente concluída.

Entregue:

- `gmxflow setup-workspace`;
- `gmxflow render-templates`;
- templates renderizados nos diretórios finais da pipeline:
  - `work/box/ions.mdp`;
  - `work/em/em.mdp`;
  - `work/nvt/nvt.mdp`;
  - `work/npt/npt.mdp`;
  - `work/prod/md.mdp`;
- perfil `smoke` com escrita de trajetória mais frequente para gerar gráficos úteis.
- `.mdp` iniciais já renderizados conforme `--profile smoke` quando usado no `startproject`.

Pendente:

- expor mais parâmetros no TOML, por exemplo:

```toml
[nonbonded]
rcoulomb_nm = 1.2
rvdw_nm = 1.2

[output]
nstenergy = 5000
nstlog = 5000
nstxout_compressed = 5000

[coupling]
temperature_groups = ["Protein", "Non-Protein"]
tau_t = [0.1, 0.1]
```

- manter `maxwarn = 0` como padrão;
- adicionar configuração explícita para `grompp.maxwarn` com justificativa quando o usuário quiser permitir warnings;
- documentar quando é necessário rodar `clean --templates` ou `clean --all-work`.

## Fase 4: Preparação Molecular Mais Robusta

Status: parcialmente implementada para proteína + peptídeo e adaptada para CHARMM em ligante pequeno.

Entregue:

- preparação simples de receptor, ligante e complexo;
- preservação de cadeias;
- histidina ajustada por regra de pH;
- nomes de histidina adaptados ao force field, incluindo `HSD/HSE/HSP` para CHARMM;
- detecção básica de pontes dissulfeto;
- prevenção de sobrescrita sem `--force`.

Pendente:

- ampliar tipos formais de `ligand_kind` além dos fluxos atuais:

```toml
ligand_kind = "peptide"
ligand_kind = "small_molecule"
ligand_kind = "none"
ligand_kind = "cofactor"
```

- adicionar modos formais de preparação:

```toml
[preparation]
mode = "simple_peptide"
```

Futuros modos:

```toml
mode = "manual"
mode = "pdbfixer"
```

- protonação manual por resíduo:

```toml
[protonation]
histidine_default = "auto"

[[protonation.overrides]]
chain = "A"
resid = 57
resname = "HIE"
```

- avaliar Biopython para parsing e seleção;
- avaliar PDBFixer/OpenMM como etapa opcional de preparação;
- documentar limites científicos da preparação automática.

## Fase 5: Ligantes Pequenos E Topologias Externas

Status: funcional para ligante já parametrizado externamente; pendente parametrização automática e robustez científica.

Objetivo: permitir sistemas proteína + molécula pequena, no estilo do tutorial Lemkul/CGenFF.

Entregue:

- suporte a ligante pequeno já parametrizado externamente com `.mol2 + .str`;
- conversor `cgenff_charmm2gmx.py` vendorizado;
- etapas `ligand-topology`, `protein-topology` e `assemble-complex`;
- integração de `.prm` e `.itp` do ligante ao `topol.top`;
- adição do ligante em `[ molecules ]`;
- normalização do moleculetype do ligante para `input.ligand_resname`;
- integração de force fields CHARMM `.ff` externos via `GMXLIB`;
- armazenamento central de force fields externos por usuário, configurável com `GMXFLOW_FORCEFIELD_DIR` e respeitando `XDG_DATA_HOME`;
- resolvedor comum para pipeline e conversor CGenFF, com precedência para force fields instalados, centralizados e cópias legadas do projeto;
- comandos `gmxflow forcefield path`, `list`, `locate`, `validate` e `install`, sem sobrescrita implícita;
- validação mínima de `forcefield.itp` e `forcefield.doc`;
- documentação e exemplos atualizados para instalar force fields uma única vez por usuário;
- resolução de force fields não instalados pelo GROMACS a partir do projeto e de diretórios de ambiente conhecidos;
- seleção do ligante pequeno por `input.ligand_resname` nas análises;
- validação de `input.ligand_resname` contra `RESI` do `.str`;
- validação da lista de átomos entre `.mol2` e `.str`;
- validação da contagem de átomos do PDB gerado contra o `.mol2`;
- aviso para penalties CGenFF altos no `.str`;
- fluxo validado end-to-end em modo `smoke`.

Configuração proposta:

```toml
[input]
ligand_kind = "small_molecule"
ligand_pdb = "inputs/ligand.pdb"
ligand_mol2 = "inputs/ligand.mol2"
ligand_str = "inputs/ligand.str"
ligand_resname = "LIG"

[force_field]
name = "charmm36-jul2022"
water = "tip3p"
```

Comando implementado:

```bash
gmxflow prepare-ligand --project project.toml
```

Responsabilidades esperadas:

- validar presença de `ligand.mol2` e `ligand.str`; (implementado)
- chamar o `cgenff_charmm2gmx.py` vendorizado; (implementado)
- organizar outputs em `work/ligand/`; (implementado)
- gerar/validar `.itp`, `.prm` e coordenadas do ligante; (implementado)
- incluir `ligand.prm` e `ligand.itp` no `topol.top`; (implementado)
- adicionar `LIG` em `[ molecules ]`; (implementado)
- checar consistência entre resname, átomos e topologia. (implementado)
- checar consistência geométrica entre PDB original e PDB gerado. (pendente)

Pendente:

- documentar passo a passo CGenFF/ParamChem/CHARMM-GUI;
- validar mais ligantes reais além de benzamidina;
- melhorar validação geométrica entre `ligand.pdb` original e PDB gerado pelo conversor;
- avaliar suporte a outras famílias de force field.

Ferramentas externas a documentar:

- CGenFF para CHARMM;
- Antechamber/GAFF ou ACPYPE para AMBER;
- ATB para GROMOS;
- LigParGen para OPLS.

## Fase 6: Análises E Figuras

Status: parcialmente concluída.

Entregue:

- comando `gmxflow analyze`;
- detecção de resíduos do ligante peptídico por cadeia;
- seleção de ligante pequeno por `input.ligand_resname`;
- criação de `lig.ndx`;
- grupos `Ligante` e `Receptor`;
- RMSD do backbone;
- RMSD do ligante;
- RMSF por resíduo;
- raio de giro;
- distância mínima receptor-ligante;
- número de contatos receptor-ligante;
- pontes de hidrogênio;
- comando `gmxflow plot-analysis`;
- painel completo em PNG;
- figuras individuais em PNG;
- comando `gmxflow report`;
- `outputs/summary.json` com estatísticas das análises;
- `outputs/summary.txt` com resumo em texto;
- `outputs/report.html` com tabela e figuras;
- publicação de figuras finais em `outputs/figures/`;
- publicação de séries `.xvg` em `outputs/data/`;
- publicação de logs em `outputs/logs/`;
- seção de execução no relatório a partir de `work/state.json`;
- comando opcional `gmxflow interaction-energy`;
- análise opcional de energia Coulomb/Lennard-Jones receptor-ligante por `gmx mdrun -rerun`;
- inclusão da energia total aproximada no relatório quando `analysis.interaction_energy = true`;
- comando opcional `gmxflow sasa`;
- análise opcional de SASA do receptor, SASA do ligante, SASA do complexo e BSA aproximado;
- inclusão de SASA/BSA no relatório quando `analysis.sasa = true`.
- gráficos individuais de SASA do complexo, SASA do ligante e BSA aproximado quando `analysis.sasa = true`;
- configuração `analysis.catalytic_residues` para calcular distância mínima e ocupação do ligante contra resíduos catalíticos;
- gráficos individuais de distância aos resíduos catalíticos e ocupação média da tríade catalítica.
- comando `gmxflow list-residues` para listar resíduos do complexo preparado e gerar uma sugestão de `catalytic_residues`.

Pendente:

- permitir customização dos gráficos;
- tratar melhor séries com poucos pontos;
- validar energia de interação por rerun em sistemas reais com diferentes versões do GROMACS.
- validar SASA/BSA em sistemas reais com diferentes versões do GROMACS.
- validar métricas de tríade catalítica em sistemas reais e documentar exemplos por família enzimática.

### Relatório Consolidado

O relatório final deve oferecer um conjunto de dados útil para interpretação de sistemas receptor-ligante a partir da simulação MD. Ele não deve copiar nem tentar se passar por relatório HADDOCK; o foco é consolidar métricas relevantes do `gmxflow`.

Implementado na primeira versão, usando dados já gerados:

- estabilidade da simulação:
  - RMSD médio e desvio do backbone;
  - RMSD médio e desvio do ligante;
  - RMSF por resíduo;
  - raio de giro médio;
  - tempo total analisado;
- interação receptor-ligante:
  - distância mínima média;
  - número médio de contatos;
  - número médio de pontes de hidrogênio;
  - fração da trajetória com contato;
  - fração da trajetória com ponte de hidrogênio;
  - energia Coulomb/Lennard-Jones receptor-ligante opcional;
  - energia total aproximada opcional;
  - SASA receptor/ligante/complexo opcional;
  - BSA aproximado opcional;
- saídas:
  - `outputs/summary.json`;
  - `outputs/summary.txt`;
  - `outputs/report.html`;
  - figuras publicadas em `outputs/figures/`;
  - séries publicadas em `outputs/data/`;
  - logs publicados em `outputs/logs/`.

Evoluções futuras:

- clustering opcional de frames/poses;
- score próprio do `gmxflow`, documentado como métrica aproximada da aplicação e não como `HADDOCK score`.

## Fase 7: Qualidade, Distribuição E Uso Real

Status: em andamento.

Entregue:

- entry point `gmxflow`;
- templates incluídos no pacote;
- README atualizado;
- suíte de testes local;
- lint local;
- exemplos versionados.

Pendente:

- CI remoto;
- licença;
- versionamento semântico;
- documentação de instalação para Windows + WSL;
- documentação de instalação de GROMACS via micromamba;
- documentação detalhada do fluxo CGenFF;
- política de compatibilidade com versões do GROMACS.
- instruções de usuário centradas em Conda/Micromamba e início do Jupyter pelo ambiente correto;
- receita e canal de distribuição Conda, após estabilizar dependências e API.

## Fase 8: Notificações De Execução

Status: proposta.

Objetivo: avisar o usuário quando pipelines longas terminarem ou falharem, sem exigir que ele monitore o terminal durante horas ou dias.

Escopo inicial proposto:

- configuração opcional em TOML:

```toml
[notifications]
email = false
smtp_host = ""
smtp_port = 587
smtp_user = ""
smtp_password_env = "GMXFLOW_SMTP_PASSWORD"
from_email = ""
to_email = ""
on_success = true
on_failure = true
```

- envio por SMTP usando `smtplib`, sem dependência extra;
- senha lida por variável de ambiente, nunca salva diretamente no `project.toml`;
- e-mail em sucesso final e/ou falha fatal;
- corpo com projeto, status, etapa final ou etapa com erro, duração, host e caminho do log;
- falha de envio tratada como aviso, nunca como falha da simulação;
- testes com monkeypatch de `smtplib.SMTP`;
- documentação com exemplo para servidor institucional e Gmail com app password.

Evoluções futuras:

- notificações por webhook;
- integração com Telegram, Slack ou Discord;
- envio de resumo com caminho para `outputs/report.html`.

## Fase 9: API Python E Experiência Jupyter

Status: implementação inicial; API e notebooks seguem experimentais.

Objetivo: permitir que cientistas configurem, executem e inspecionem um fluxo de dinâmica molecular no notebook usando conceitos e mensagens do domínio científico, sem precisar conhecer comandos internos, TOML ou detalhes do executor.

Princípios:

- criar uma API Python de domínio original, inspirada em boas práticas de interfaces científicas como gmxapi, sem copiar sua API nem sua arquitetura;
- expor objetos e métodos com nomes científicos explícitos, mantendo a CLI como interface complementar para automação e usuários avançados;
- oferecer configuração progressiva e compreensível, sem esconder parâmetros que alterem decisões científicas;
- tornar resultados verificáveis no próprio notebook: validações, progresso por etapa, logs, figuras, tabelas, relatório e arquivos exportáveis;
- apresentar erros acionáveis em linguagem clara, com a etapa e a correção provável;
- priorizar Jupyter Notebook/JupyterLab local; Colab fica fora do escopo inicial.

Fluxo conceitual desejado — nomes e assinaturas ainda serão definidos:

```python
project = GmxFlowProject.from_files(receptor="receptor.pdb", ligand="ligand.pdb")
project.configure(profile="smoke", force_field="amber99sb-ildn")
validation = project.validate()
run = project.run()
run.results.show()
run.results.save("results/")
```

Entregas propostas:

- separar uma camada Python pública da camada Typer, para CLI e notebooks usarem o mesmo núcleo (primeiro recorte implementado; contrato ainda experimental);
- definir ciclo de vida e modelos públicos para projeto, configuração, validação, execução e resultados (parcialmente implementado);
- gerar `project.ipynb` em `gmxflow startproject` e manter cada notebook junto ao respectivo projeto em `examples/` (primeiro recorte implementado);
- evoluir o notebook introdutório com seleção de arquivos e configuração guiada;
- pré-validar entradas, dependências e plano antes de iniciar tarefas longas;
- incluir um exemplo `smoke` e um exemplo científico representativo, distinguindo teste de fluxo e simulação interpretável;
- documentar estabilidade, versionamento e exemplos da API pública.

## Fase 10: Distribuição Conda/Micromamba Para Usuários

Status: proposta.

Objetivo: fazer de Conda/Micromamba o caminho padrão de instalação e suporte para usuários científicos, sem exigir que aprendam conceitos de ambientes de desenvolvimento versus produção.

Entregas propostas:

- documentar uma instalação curta no ambiente que já contém GROMACS e uma configuração guiada para quem ainda não tem esse ambiente;
- fornecer especificação de ambiente reproduzível para `gmxflow`, Python e ferramentas Jupyter, sem forçar uma build de GROMACS incompatível com o hardware disponível;
- testar instalação e seleção do kernel Jupyter em Conda e Micromamba;
- avaliar empacotamento e publicação Conda depois de estabilizar a API e as dependências;
- explicar instalação, atualização e remoção como tarefas simples de usuário, sem separar a documentação em fluxos de desenvolvimento e produção.

Fora do escopo inicial:

- hospedar uma API HTTP;
- prometer disponibilidade de GPU ou executar jobs em infraestrutura gerenciada pelo `gmxflow`;
- automatizar compilação de GROMACS com CUDA para qualquer máquina.

## Prioridade Recomendada

Ordem prática para os próximos passos:

1. Definir a API Python pública de domínio para projeto, configuração, validação, execução e resultados.
2. Separar essa API do Typer, fazendo CLI e Jupyter compartilharem o mesmo núcleo.
3. Validar o notebook gerado e os exemplos físicos em ambientes Conda/Micromamba suportados; revisar e estabilizar o contrato da API antes de ampliar a experiência guiada.
4. Consolidar a instalação Conda/Micromamba para usuário final e testar kernel, GROMACS e `gmxflow` no mesmo ambiente.
5. Validar energia de interação, SASA/BSA e métricas catalíticas em simulações reais completas.
6. Melhorar validações de ligante pequeno, incluindo consistência geométrica entre `ligand.pdb` original e PDB gerado pelo conversor.
7. Documentar fluxo CGenFF/ParamChem/CHARMM-GUI em detalhe e melhorar mensagens para force field ausente.
8. Expor parâmetros adicionais dos `.mdp` no TOML e aprimorar erros/recomendações de retomada e limpeza.
9. Preparar empacotamento Conda depois de estabilizar a API e as dependências.
10. Configurar CI remoto, licença e política de versionamento semântico.
11. Documentar instalação para Windows + WSL e compatibilidade com versões do GROMACS.
12. Documentar um fluxo HADDOCK -> gmxflow para triagem por pose representativa de cluster.
13. Implementar protonação manual por resíduo; avaliar Biopython e PDBFixer/OpenMM.
14. Implementar notificações opcionais de execução por e-mail.
15. Avaliar clustering opcional e métricas avançadas, sem chamar score próprio de `HADDOCK score`.

## Critério De Maturidade

O `gmxflow` pode ser considerado pronto para uso mais amplo quando:

- [x] tiver execução real com logs;
- [x] conseguir retomar etapas;
- [x] detectar quando uma etapa precisa ser refeita por mudança de entrada/configuração rastreada;
- [~] validar entradas e saídas de forma clara;
- [~] documentar claramente as limitações;
- [x] tiver testes cobrindo preparação, pipeline, análise e CLI;
- [~] suportar proteína + peptídeo de forma robusta;
- [~] suportar proteína + ligante pequeno com topologia externa;
- [x] deixar explícito quando o sistema exige parametrização externa;
- [x] produzir resultados organizados em `outputs/`.

Legenda:

- `[x]` atendido no escopo atual;
- `[~]` parcialmente atendido, mas ainda precisa de validação em casos reais, documentação ou robustez adicional;
- `[ ]` pendente.
