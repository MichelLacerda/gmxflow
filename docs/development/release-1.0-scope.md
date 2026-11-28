# Direção e plano de migração para a versão 1.0.0

Status: direção arquitetural aprovada para o sandbox; os exemplos de API abaixo
são pseudocódigo e não descrevem necessariamente o comportamento já implementado.
Esta versão pode introduzir break changes. O objetivo é chegar a um desenho
coeso e remover o caminho antigo, não manter APIs paralelas por
retrocompatibilidade.

## Objetivo do produto

O principal diferencial do gmxflow é oferecer uma organização de projeto
consistente, intuitiva e sem redundância, inspirada em convenções Unix. Entradas,
parâmetros, arquivos intermediários, logs e resultados devem ter locais
previsíveis, relações explícitas e uma única origem de verdade.

Sobre essa organização, o gmxflow deve oferecer:

- configuração centralizada e legível para escolhas compartilhadas pelo projeto;
- composição explícita de etapas científicas em uma pipeline;
- construção e inspeção de comandos GROMACS sem exigir que o usuário conheça
  todos os detalhes do CLI;
- execução reproduzível, com logs, estado e artefatos rastreáveis;
- uso equivalente pelo Python interativo, Jupyter e CLI.

GROMACS continua sendo o backend de dinâmica molecular. Reimplementar o
GROMACS em Rust ou trocar o backend não faz parte deste escopo: só se reconsidera
essa decisão diante de uma limitação concreta, demonstrada e mensurada.

## Decisões arquiteturais e motivações

### 1. Uma forma principal de compor e executar

O usuário deve montar um workflow explícito. A CLI e o Jupyter usam o mesmo
modelo de domínio e execução; a CLI não mantém uma pipeline oculta ou
alternativa. Não deve existir um `run_workflow()` que esconda a composição
inteira nem dois caminhos equivalentes mantidos por compatibilidade.

**Motivação:** a sequência de trabalho precisa ser compreensível, inspecionável
e auditável por quem usa ou revisa o projeto. A automação pode facilitar a
composição, mas não deve ocultar decisões científicas ou a ordem real das
operações.

### 2. `Project` delega composição a `PipelineBuilder`

O objeto `Project` representa o projeto, sua configuração e seus caminhos. A
composição vive em `project.pipeline`, delegada a um `PipelineBuilder`, em vez
de acumular métodos de execução no próprio `Project`.

```python
from gmxflow.project import Project

project = Project.open("project.toml")

workflow = (
    project.pipeline
    .prepare()
    .topology()
    .solvate(box_size_nm=1.0)
    .minimize(maxwarn=0)
)

workflow.info()                 # resumo legível, não executa
command_plan = workflow.commands()  # plano de comandos, não executa
result = workflow.run()          # fronteira explícita de efeitos externos
```

Os nomes e parâmetros são ilustrativos. Os métodos para Steps internos devem
ser explícitos e tipados para permitir autocomplete e descoberta pela IDE. A
composição é lazy e imutável: encadear chamadas apenas descreve o workflow; não
cria diretórios, não altera arquivos e não inicia processos.

**Motivação:** a interface lembra a ergonomia de uma query lazy de ORM —
construir e inspecionar não executa — sem copiar literalmente o Django. Métodos
explícitos deixam clara a diferença entre descrever, inspecionar e executar.
Evitar `__getattr__` dinâmico e registro global de plugins na primeira versão,
pois reduzem a tipagem, o autocomplete e a clareza sobre quais operações são
suportadas. Um registro interno só se justifica se eliminar duplicação real sem
esconder a API.

### 3. Steps como classes extensíveis

Steps internos e personalizados são classes que implementam um contrato comum
estrutural definido por `Step(Protocol)`. Uma implementação pode herdar de
`Step` para explicitar a intenção e receber suporte de tipagem, mas o executor
deve depender do contrato, não de herança em runtime. O builder oferece métodos
convenientes para os Steps internos; `.then()` permite fornecer uma classe
customizada e parâmetros, deixando a instanciação ao mecanismo do workflow.

```python
class ContactAnalysis(Step):
    def __init__(self, cutoff_nm: float = 0.4) -> None:
        self.cutoff_nm = cutoff_nm

    def info(self) -> StepInfo:
        ...

    def commands(self, context: StepContext) -> tuple[Command, ...]:
        ...


workflow = (
    project.pipeline
    .prepare()
    .then(ContactAnalysis, cutoff_nm=0.5)
)
```

O contrato final de `Step` ainda precisa ser definido no código: identidade,
parâmetros rastreáveis, entradas/saídas, descrição e construção de comandos.
Contexto de projeto e caminhos resolvidos devem ser fornecidos pelo builder ou
executor no momento apropriado, sem estado global e sem exigir que o autor do
Step construa manualmente toda a infraestrutura.

**Motivação:** classes tornam explícitos os comportamentos e permitem extensão
por usuários que dominem Python e GROMACS, sem fragmentar o núcleo em dezenas de
callbacks ou funções soltas. Não exigir registro global para usar um Step
customizado reduz configuração incidental. `info()` deve retornar dados
estruturados/legíveis e nunca executar; decisões científicas e parâmetros que
afetam saídas devem ser visíveis e rastreáveis.

### 4. Pipeline linear na 1.0.0

A composição da versão 1.0.0 é linear. Não implementar `Parallel`, ramos,
junções, condição `Branch`, flag de elegibilidade paralela ou concorrência
implícita nesta versão.

```python
workflow = (
    project.pipeline
    .prepare()
    .topology()
    .solvate()
    .minimize()
    .equilibrate_nvt()
    .equilibrate_npt()
    .production_md()
    .analyze_rmsd()
    .report()
)
```

**Motivação:** paralelismo e grafo geral aumentam a superfície de validação,
execução, retomada e apresentação sem serem necessários para estabelecer o
contrato principal. A sequência linear é mais fácil de explicar e auditar. A
expansão para DAG poderá ser reavaliada depois, com um caso de uso concreto e
independente — por exemplo, análises realmente independentes e uma junção
posterior — e sem confundir paralelismo com ramificação condicional.

### 5. `Command` como modelo de processo construível e executável

`Command` é uma classe-base abstrata. `GromacsCommand` especializa o contrato
para chamadas GROMACS; outros comandos podem ser implementados por extensões.
Construir um comando não o executa. Um comando pode ser inspecionado e também
executado isoladamente em Python, IPython, Jupyter ou depurador.

```python
command = (
    GromacsCommand("grompp")
    .input("topology", "work/topology/topol.top")
    .input("coordinates", "work/system/solvated.gro")
    .output("tpr", "work/em/em.tpr")
    .option("maxwarn", 0)
    .build()
)

command.info()          # argv, cwd e entradas/saídas declaradas
result = command.run()  # executa e retorna código, streams e duração
```

O resultado de `build()` deve ser uma especificação imutável do processo
(`CommandSpec` ou equivalente): executável, argumentos como sequência, diretório
de trabalho, ambiente, stdin e artefatos declarados. Não montar comandos como
string de shell nem usar `shell=True`. Opções GROMACS ainda não mapeadas podem
ser informadas explicitamente; opções tipadas e extras conflitantes não podem
se sobrescrever silenciosamente.

`Command.run()` e `Workflow.run()` compartilham o mesmo executor de baixo nível.
O comando isolado retorna resultado e erros úteis, mas não promete estado ou
retomada do workflow. O workflow agrupa comandos por Step e acrescenta logs,
validação de artefatos, fingerprints e retomada. Um Step pode construir vários
comandos; não pressupor um comando por etapa.

**Motivação:** o padrão de builder/lazy-command oferece a ergonomia de
inspecionar a chamada antes de executá-la (`command.info()`), sem trocar o
executor confiável por uma biblioteca de sintaxe. A biblioteca padrão
`subprocess` continua adequada por trás do executor síncrono; plumbum, `sh`,
Invoke, AnyIO e `gmxapi` não são requisitos desta arquitetura. Uma integração
opcional poderá ser avaliada separadamente se surgir necessidade comprovada.

### 6. Projeto, contexto científico e configuração

`project.toml` mantém escolhas compartilhadas do projeto, como sistema,
force field, entradas e configurações comuns. `ligand_kind` continua sendo
contexto científico importante para validar compatibilidade e requisitos de
etapas; não deve escolher uma receita completa nem impedir composição modular.
O usuário decide quais Steps incluir e em que ordem.

Parâmetros GROMACS usados com frequência devem gradualmente ganhar campos
nomeados, tipos, documentação e validação. O construtor de comandos também deve
permitir opções explícitas ainda não mapeadas, preservando acesso a capacidades
do GROMACS que o gmxflow não modele. Fornecer opção não mapeada não equivale a
validação científica pelo gmxflow.

**Motivação:** separar contexto do sistema, parâmetros do projeto, sequência
de operações e argumentos de baixo nível evita tanto receitas rígidas quanto
uma configuração monolítica que tenta antecipar todos os usos. Defaults que
alterem force field, protonação, amostragem ou interpretação científica não
podem ser introduzidos silenciosamente.

### 7. Módulos por responsabilidade; sem módulo genérico `api`

Não manter `api.py` como fachada genérica ou depósito de tipos. Expor conceitos
concisos a partir dos módulos responsáveis:

```python
from gmxflow.project import Project
from gmxflow.pipeline import PipelineBuilder, Step, Workflow
from gmxflow.command import Command, GromacsCommand
```

O layout exato pode mudar conforme as responsabilidades se estabilizam, mas
projeto, configuração, composição, comandos, execução e apresentação devem
permanecer separáveis. A migração não deve consistir apenas em mover todo o
conteúdo de `api.py` para `project.py`.

**Motivação:** imports devem revelar a responsabilidade do objeto e evitar
acoplamento circular ou um módulo público que esconda onde o comportamento
vive. Não criar aliases antigos apenas para preservar compatibilidade no
sandbox.

## Plano de migração

Cada etapa é uma unidade revisável. Atualizar implementação, testes e
documentação do contrato alterado; após validar o caminho novo, remover o
caminho antigo e seus testes/documentos exclusivos. Não começar várias etapas
em um único bloco sem revisão humana.

### Etapa 1 — Fixar contratos de domínio

**Escopo:** definir os contratos mínimos de `Project`, `Step(Protocol)`, `Workflow`,
`Command`, especificação de comando, contexto e resultado; separar interfaces de
implementação e efeitos externos.

**Não escopo:** migrar todos os Steps ou alterar escolhas científicas.

**Aceite:** imports por domínio claros; composição e inspeção sem efeitos
colaterais; erros/valores de retorno documentados; testes unitários para
contratos e serialização de estado relevante.

### Etapa 2 — Criar `PipelineBuilder` lazy e linear

**Escopo:** `Project.open("project.toml")`, `project.pipeline`, métodos
explícitos para os Steps internos já suportados e `.then(CustomStep, ...)`.

**Não escopo:** plugins autodetectados, registro global, execução paralela ou
montagem automática de uma receita inteira.

**Aceite:** encadeamento preserva ordem e não toca no disco; classe inválida,
argumentos inválidos e incompatibilidade de entradas são reportados antes de
executar; `info()` mostra a sequência resultante.

### Etapa 3 — Construir comandos como objetos

**Escopo:** classe-base abstrata `Command`, implementação `GromacsCommand`, opções
tipadas e extras, `build()`, `info()` e especificação imutável com argv separado.

**Não escopo:** migrar ainda toda execução antiga ou adicionar uma biblioteca
externa de subprocessos.

**Aceite:** argv determinístico; ausência de shell; conflitos de opções
rejeitados; comando construído pode ser inspecionado sem execução.

### Etapa 4 — Unificar a execução

**Escopo:** `Command.run()` e `Workflow.run()` delegam ao mesmo executor; logs,
erros associados a Step, arquivos de entrada/saída, fingerprints e retomada
continuam explícitos.

**Não escopo:** concorrência, substituição obrigatória do `subprocess` da
biblioteca padrão ou integração obrigatória com `gmxapi`.

**Aceite:** comando isolado executa sem alegar estado de workflow; workflow
executa em ordem linear; falha impede sucessores; outputs preservados conforme
as regras de não sobrescrita; logs e estado permitem auditoria e retomada.

### Etapa 5 — Migrar Steps, CLI, notebooks e exemplos

**Escopo:** migrar gradualmente Steps existentes para classes e comandos; CLI
e Jupyter compõem o mesmo Workflow; atualizar projeto de exemplo e documentação
de uso.

**Não escopo:** modificar parâmetros científicos para aproximar tutoriais sem
uma decisão explícita e validação humana.

**Aceite:** exemplos mostram composição explícita; CLI não contém pipeline
alternativa; notebooks funcionam com a mesma API pública; smoke permanece
identificado como teste de integração, não evidência de validade científica.

### Etapa 6 — Remover legado e declarar o escopo da release

**Escopo:** apagar `api.py` e aliases antigos, `run_workflow`, grafo e
`Parallel` se ainda existirem, caminhos duplicados de execução e testes/docs
que só cubram esses desenhos. Auditar referências e fechar o escopo público.

**Aceite:** uma forma documentada de compor e executar; nenhum import ou teste
depende de APIs removidas; suíte focada passa; lint e verificação estática
passam; matriz de ambientes e limites científicos da release estão declarados.

## Fora do escopo da 1.0.0

- Reimplementar GROMACS em Rust ou substituir seu backend.
- Tornar `gmxapi`, ParmEd, RO-Crate ou CWL dependências do núcleo. ParmEd pode
  ser avaliado para interoperabilidade de topologias; RO-Crate para proveniência;
  CWL para exportação de workflows. Conversões e metadados não provam equivalência
  científica, e CWL só deve ser avaliado depois de estabilizar os contratos.
- DAG genérico, `Parallel`, execução concorrente ou condicional.
- Automatizar escolhas científicas ou prometer suporte universal a sistemas,
  ligantes, force fields e fluxos GROMACS.

## Revisão científica e humana

Force field, protonação, parametrização de ligantes, parâmetros de simulação,
métodos de análise e interpretação de resultados exigem revisão humana. A
refatoração de arquitetura não autoriza alteração implícita desses elementos.
O responsável pelo código deve compreender integralmente cada contribuição,
incluindo código assistido por IA, e verificar as evidências de teste.
