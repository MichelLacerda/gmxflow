# Primeiro Recorte: Fluxo Jupyter De Validação

Status: primeiro fluxo implementado. O projeto [smoke para Jupyter](../../examples/smoke_peptide_complex/project.ipynb)
está fisicamente disponível em `examples/`, junto com seu `project.toml` e os
arquivos de entrada. O notebook trabalha diretamente no exemplo versionado,
sem copiar projetos durante a execução. `gmxflow startproject` também gera
`project.ipynb` em novos projetos. O fluxo foi executado de ponta a ponta com
Python 3.12.16 e GROMACS 2026.3. A API e o notebook continuam experimentais; o
smoke verifica integração do software, não validade científica.

## Objetivo

Definir um primeiro fluxo pequeno e reproduzível para validar a experiência Jupyter do `gmxflow` antes de desenhar uma interface mais ampla. O fluxo usa o exemplo existente `examples/smoke_peptide_complex` e serve apenas para verificar integração e usabilidade do software.

## História De Usuário

Como cientista com Jupyter, Python, `gmxflow` e GROMACS disponíveis no mesmo ambiente Conda/Micromamba, quero abrir um notebook, verificar os pré-requisitos, executar um exemplo e abrir o relatório sem precisar conhecer ou digitar comandos da CLI nem escrever código de infraestrutura.

## Dentro Do Escopo

- Manter os notebooks junto dos projetos em `examples/`, sem cópias paralelas em `notebooks/`.
- Gerar `project.ipynb` junto com `project.toml` pelo comando `gmxflow startproject`.
- Prever uma etapa explícita de validação antes de iniciar a execução; por ser um exemplo smoke fixo, não exigir a inspeção manual dos detalhes internos de cada etapa.
- Executar o fluxo `smoke` por meio da API experimental `GmxFlowProject`, sem invocar a CLI ou `subprocess` diretamente no notebook.
- A execução da API valida entradas, force field e executável GROMACS antes de preparar o workspace; preserva templates existentes e reutiliza logs e estado do executor.
- Mostrar sucesso/falha e acesso ao relatório e aos arquivos gerados; falhas devem apontar a etapa e o log correspondente.
- Preservar configuração e entradas do projeto ao executar; arquivos gerados devem ficar em `work/` e `outputs/`, que são regeneráveis e ignorados pelo Git.
- Permitir executar o notebook de cima a baixo em um kernel Conda/Micromamba limpo, com células curtas e falhas compreensíveis.

## Fora Do Escopo

- Interpretar os resultados como dinâmica molecular cientificamente válida. O exemplo `smoke` usa apenas 10 passos e valida integração, não amostragem ou propriedades físicas.
- Escolher ou alterar force field, protonação, parâmetros científicos ou métodos de análise.
- Criar automaticamente ambientes Conda/Micromamba ou instalar dependências a partir do notebook.
- Suportar Colab, GPU obrigatória, parametrização automática de ligantes, nem um fluxo de produção com estruturas fornecidas pelo usuário.
- Adicionar visualização interativa 3D ou análise de trajetórias via bibliotecas extras; isso será avaliado numa tarefa futura.
- Definir nomes de classes, métodos ou assinaturas antes de uma tarefa separada de desenho e revisão do contrato da API.

## Critérios De Aceite

1. O notebook informa os pré-requisitos e valida GROMACS, force field e arquivos necessários antes da execução.
2. Os projetos para notebook incluem fisicamente a configuração e as entradas; não há cópia de projeto em tempo de execução.
3. A execução preserva `project.toml` e os arquivos de entrada, mantendo artefatos gerados em `work/` e `outputs/`.
4. `startproject` cria `project.ipynb` e não sobrescreve arquivos existentes sem `--force`.
5. A interface do notebook usa a API do pacote; não exige que a pessoa conheça comandos da CLI nem esconde uma invocação de shell como se fosse API Python.
6. O notebook expõe sucesso/falha e acesso ao relatório sem exigir que a pessoa interprete detalhes internos da pipeline.
7. As células executam de cima a baixo em um kernel limpo quando os pré-requisitos estão presentes; erros são apresentados com contexto acionável.
8. A documentação identifica claramente o fluxo como `smoke` e proíbe interpretar seus resultados como evidência científica.
9. Testes automatizados cobrem os comportamentos não dependentes de GPU; eventual teste end-to-end com GROMACS é identificado separadamente e não substitui revisão científica.

## Decisões E Revisões Humanas

- Esta proposta escolhe o exemplo smoke apenas como primeira prova da experiência de software. Um notebook científico representativo será uma tarefa independente, escolhida e validada com revisão humana.
- Para uma etapa futura de notebook científico/visualização, considerar `MDAnalysis` para leitura e análise de estruturas/trajetórias, `NGLView` para visualização molecular 3D interativa e `ipywidgets` para controles interativos. São candidatas, não dependências aprovadas; avaliar compatibilidade com JupyterLab e Conda/Micromamba, custo de instalação e limites de uso antes de adotá-las.
- As candidatas complementariam as figuras estáticas já produzidas pelo `gmxflow`; esta proposta não troca nem altera a análise científica existente.
- A pessoa revisora deve aprovar este percurso antes de se fixarem classes, métodos e estabilidade da API pública.
- Nenhuma conclusão sobre desempenho, qualidade de parâmetros ou validade científica pode ser derivada deste fluxo.

## Próxima Tarefa

Ampliar a validação da experiência em outras combinações suportadas de Python e GROMACS e documentar a instalação do kernel para o notebook. Depois, revisar com humanos o contrato experimental da API antes de declará-la estável. O teste de integração real já foi executado com sucesso em uma combinação de ambiente; subprocessos continuam sendo usados internamente pelo executor compartilhado.
