# Escopo Proposto Para A Versão 1.0.0

Status: rascunho para revisão humana. Este documento registra uma proposta de
escopo e uma avaliação inicial do `gmxapi`; não declara a versão 1.0 pronta nem
torna a API atual estável.

## Estado Verificado

- No momento desta revisão, a branch `1.0.0-dev` e `main` apontam para o mesmo
  commit.
- A cópia de trabalho de [pyproject.toml](../../pyproject.toml) declara agora
  `1.0.0`; a alteração está fora do escopo desta avaliação e, por si só, não
  estabelece prontidão para release.
- `GmxFlowProject.open()`, `plan()`, `validate()` e `run()` permitem abrir a
  configuração, inspecionar o plano, validar pré-requisitos e executar etapas
  liberadas usando o executor compartilhado. `run()` retorna resultados
  estruturados com caminhos de logs; a API permanece experimental. O smoke
  passou em uma execução de ponta a ponta com Python 3.12.16 e GROMACS 2026.3,
  mas a matriz de ambientes ainda precisa ser validada.
- O projeto [smoke para Jupyter](../../notebooks/smoke_peptide_complex/project.ipynb)
  foi executado de cima a baixo com o kernel Micromamba. A pasta contém uma
  cópia física do exemplo; o notebook não copia arquivos em tempo de execução.
- O executor executa cada etapa por `subprocess.run`. Algumas etapas invocam
  comandos internos `gmxflow`; outras invocam ferramentas GROMACS.
- As análises também chamam ferramentas GROMACS por `subprocess.run`, incluindo
  `make_ndx`, `rms`, `rmsf`, `gyrate`, `mindist`, `hbond`, `sasa` e `energy`.

Esses pontos refletem o código existente, em especial
[api.py](../../src/gmxflow/api.py), [executor.py](../../src/gmxflow/executor.py),
[pipeline.py](../../src/gmxflow/pipeline.py) e
[analysis.py](../../src/gmxflow/analysis.py).

## Avaliação Inicial Do `gmxapi`

A documentação oficial consultada é a do GROMACS 2026.4:

- [Uso do pacote Python](https://manual.gromacs.org/current/gmxapi/userguide/usage.html)
- [Referência da API Python](https://manual.gromacs.org/current/gmxapi/userguide/pythonreference.html)
- [Instalação do pacote Python](https://manual.gromacs.org/current/gmxapi/userguide/install.html)

O `gmxapi` fornece uma interface Python de alto nível e uma extensão C++ de
nível mais baixo. A operação `gmxapi.mdrun()` executa uma simulação a partir de
um TPR pela integração com o módulo de dinâmica molecular do GROMACS. Porém, a
documentação descreve `gmxapi.commandline_operation()` como uma operação que
executa um subprocesso em um subdiretório gerado automaticamente. Ela é o
mecanismo disponível para vários comandos GROMACS que não têm uma operação
Python integrada.

Portanto, usar `gmxapi` não significa eliminar subprocessos de todo o fluxo.
Pode substituir a chamada direta do gmxflow a `mdrun` por uma operação Python
integrada, e pode representar outros comandos como operações do grafo, mas
esses comandos continuam sendo processos externos. A API pública do gmxflow
pode, por sua vez, oferecer uma experiência simples no notebook sem expor
comandos, independentemente do mecanismo interno usado pelo executor.

A instalação também afeta a promessa para usuários Conda/Micromamba: a
documentação oficial informa que o pacote Python contém código C++ compilado
contra uma instalação GROMACS específica, que requer suporte `GMXAPI` e
bibliotecas compartilhadas. A documentação considera Conda uma alternativa
possível, mas não cobre uma receita Conda e alerta que compatibilidade de
toolchain/MPI pode complicar o ambiente. A instalação de `gmxapi` precisa ser
testada com as variantes de GROMACS que o gmxflow pretende suportar, inclusive
com o fluxo CUDA documentado pelo projeto.

## Decisão De Arquitetura Para A 1.0

1. Não prometer que a versão 1.0 elimina subprocessos.
2. Tratar `gmxapi` como uma integração opcional a ser validada em um protótipo
   separado, começando por `mdrun`; não torná-lo dependência obrigatória até
   validar instalação e compatibilidade nos ambientes Conda/Micromamba visados.
3. Manter a API pública do gmxflow como a interface humana do notebook. Ela
   pode chamar o núcleo Python compartilhado com a CLI, preservando logs,
   retomada, estado e erros por etapa. A execução de comandos GROMACS pode
   continuar encapsulada pelo executor atual enquanto essa integração é
   avaliada.
4. Manter `gmxapi` fora da dependência obrigatória da 1.0; uma possível
   extensão para `mdrun` fica para protótipo e validação futuros.

Essa decisão é de arquitetura e instalação, não altera métodos ou interpretação
científica. Adoção futura de `gmxapi` ainda exige revisão humana e validação nos
ambientes Conda/Micromamba visados.

## Alternativas Para Executar Comandos Externos

O executor atual já envia uma sequência de argumentos sem shell, define
`cwd`, ambiente e `stdin`, captura `stdout`/`stderr` e código de saída, e usa
esses dados para logs, estado e retomada. Qualquer substituto precisa preservar
essas propriedades; uma sintaxe mais curta não é suficiente.

| Opção | O que oferece | Adequação ao executor atual |
| --- | --- | --- |
| `subprocess` (stdlib) | Execução direta com argv e controle explícito; sem dependência adicional. | Já atende ao contrato síncrono necessário e é a escolha para a 1.0. |
| Plumbum | Objetos de comando, composição de argumentos e conveniências de diretório/ambiente; `run()` pode expor código, stdout e stderr. | É a alternativa mais próxima de uma camada de ergonomia para comandos locais, mas acrescenta uma dependência e exige adaptar captura de `stdin`, ambiente, códigos de saída e caminhos. Não elimina processos externos. |
| `sh` | Chama executáveis com uma sintaxe semelhante a funções Python e oferece opções especiais para I/O, diretório, ambiente e timeout. | Não é candidato para a promessa multiplataforma: a documentação declara que Windows não é suportado. O modelo dinâmico e a forma de configurar ambiente também diferem do contrato atual. |
| Invoke | Runner com captura de streams, timeout, interação e organização de tarefas. | É orientado a tarefas de automação e recebe comandos como strings de shell. Isso não combina com o modelo atual de argv e exigiria quoting/serialização, adicionando risco sem benefício necessário para chamadas de uma pipeline. |
| AnyIO | `run_process()`/`open_process()` com argv e suporte a execução assíncrona e streams. | Faz sentido se a API pública passar a ser assíncrona e precisar integrar-se a um event loop ou cancelar/acompanhar processos. A pipeline atual é sequencial e síncrona; introduzir async agora aumentaria a complexidade para notebooks sem remover subprocessos. |

Documentação consultada: [Plumbum local commands](https://plumbum.readthedocs.io/en/latest/local_commands.html),
[`sh` documentação e FAQ](https://sh.readthedocs.io/en/latest/),
[Invoke runners](https://docs.pyinvoke.org/en/stable/api/runners.html) e
[AnyIO subprocesses](https://anyio.readthedocs.io/en/stable/subprocesses.html).

### Recomendação Para A 1.0

Manter `subprocess` da biblioteca padrão como mecanismo interno para a 1.0. O
executor existente já recebe argv, diretório, ambiente e stdin, e registra
código, stdout e stderr. Não adicionar adaptador nem biblioteca externa sem
uma necessidade demonstrada; isso preserva o comportamento conhecido e evita
uma dependência extra no caminho Conda/Micromamba. Não usar `shell=True` nem
converter os comandos em strings de shell para obter sintaxe mais curta.

## Escopo Mínimo Candidato Para 1.0

- Uma API Python documentada e estável para abrir, validar, planejar e executar
  um projeto e inspecionar seus resultados.
- A CLI existente mantida como interface complementar, compartilhando o mesmo
  núcleo de domínio e execução.
- Um percurso Jupyter/JupyterLab reproduzível, executável de cima a baixo,
  que valida pré-requisitos e mostra plano, progresso, logs e saídas.
- Execução do exemplo `smoke` em cópia/diretório de trabalho isolado, sem
  sobrescrita implícita e identificada explicitamente como teste de integração
  não interpretável cientificamente.
- Instalação Conda/Micromamba testada com uma faixa declarada de Python e
  GROMACS, kernel Jupyter selecionável e documentação apropriada para usuários
  sem experiência de desenvolvimento Python.
- Testes unitários sem GPU, teste de integração reproduzível com GROMACS, CI,
  licença e documentação dos limites científicos e técnicos do escopo
  suportado.

Este escopo ainda precisa de uma decisão humana sobre quais fluxos científicos
serão considerados oficialmente suportados na 1.0 (proteína + peptídeo,
proteína + molécula pequena preparada externamente, ou ambos), e sobre se
métricas opcionais como energia de interação e SASA/BSA terão status suportado
ou experimental.

## Próximas Tarefas De Implementação

1. Validar a experiência Jupyter em outras combinações de Python/GROMACS e
   documentar uma matriz suportada de ambientes Conda/Micromamba.
2. Revisar o contrato da API experimental antes de estabilizá-lo para a 1.0.
3. Avaliar `gmxapi` futuramente como extensão opcional para `mdrun`, em um
   protótipo isolado; não é dependência nem requisito da versão 1.0.

Cada tarefa deve preservar a retomada, a trilha de logs, os nomes das etapas e
os parâmetros científicos já definidos. A API experimental agora valida e
executa por meio do executor compartilhado; isso ainda não constitui contrato
estável nem substitui integração real com GROMACS e revisão humana.
