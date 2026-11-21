# Primeiro Recorte: Fluxo Jupyter De Validação

Status: implementação incremental. A API experimental permite abrir, inspecionar, validar e executar um projeto usando o executor compartilhado com a CLI. `ExecutionReport` expõe os resultados da preparação do workspace e de cada etapa, com seus logs. A interface pública ainda não é estável, e o notebook de ponta a ponta continua pendente.

## Objetivo

Definir um primeiro fluxo pequeno e reproduzível para validar a experiência Jupyter do `gmxflow` antes de desenhar uma interface mais ampla. O fluxo usa o exemplo existente `examples/smoke_peptide_complex` e serve apenas para verificar integração e usabilidade do software.

## História De Usuário

Como cientista com Jupyter, Python, `gmxflow` e GROMACS disponíveis no mesmo ambiente Conda/Micromamba, quero abrir um notebook, verificar os pré-requisitos, validar e pré-visualizar o exemplo, executá-lo e inspecionar o estado, os logs e o relatório sem precisar conhecer ou digitar comandos da CLI.

## Dentro Do Escopo

- Usar `examples/smoke_peptide_complex` como entrada fixa do primeiro percurso, sem pedir ao usuário que edite TOML ou escreva comandos de terminal dentro do notebook.
- Prever uma etapa explícita de validação e uma etapa de pré-visualização antes de iniciar a execução.
- Executar o fluxo `smoke` por meio da futura API Python pública, não invocando a CLI por shell ou `subprocess` no notebook.
- A execução da API valida entradas, force field e executável GROMACS antes de preparar o workspace; preserva templates existentes e reutiliza logs e estado do executor.
- Mostrar estado final, caminho de logs e localização dos resultados/relatório; falhas devem apontar a etapa e o log correspondente.
- Manter os arquivos versionados do exemplo intactos: execução e outputs devem ocorrer em uma cópia ou diretório de trabalho separado, sem sobrescrita implícita.
- Permitir executar o notebook de cima a baixo em um kernel limpo, com todas as células concluindo ou apresentando falhas compreensíveis.

## Fora Do Escopo

- Interpretar os resultados como dinâmica molecular cientificamente válida. O exemplo `smoke` usa apenas 10 passos e valida integração, não amostragem ou propriedades físicas.
- Escolher ou alterar force field, protonação, parâmetros científicos ou métodos de análise.
- Criar automaticamente ambientes Conda/Micromamba ou instalar dependências a partir do notebook.
- Suportar Colab, GPU obrigatória, parametrização automática de ligantes, nem um fluxo de produção com estruturas fornecidas pelo usuário.
- Adicionar visualização interativa 3D ou análise de trajetórias via bibliotecas extras; isso será avaliado numa tarefa futura.
- Definir nomes de classes, métodos ou assinaturas antes de uma tarefa separada de desenho e revisão do contrato da API.

## Critérios De Aceite Da Implementação Futura

1. O notebook informa os pré-requisitos e valida kernel, dependências, GROMACS e arquivos necessários antes da execução.
2. A pessoa consegue revisar a configuração/plano antes de iniciar as etapas que executam GROMACS.
3. A execução não altera os arquivos versionados do exemplo nem sobrescreve dados do usuário sem uma ação explícita.
4. A interface do notebook usa a API pública do pacote; não exige que a pessoa conheça comandos da CLI, nem esconde uma invocação de shell como se fosse API Python.
5. O notebook expõe sucesso/falha, etapa atual ou final, logs e caminhos dos resultados/relatório de forma legível.
6. As células executam de cima a baixo em um kernel limpo quando os pré-requisitos estão presentes; erros de pré-requisito ou execução são apresentados com contexto acionável.
7. A documentação e o notebook identificam claramente o fluxo como `smoke` e proíbem interpretar seus resultados como evidência científica.
8. Testes automatizados cobrem os comportamentos não dependentes de GPU; eventual teste end-to-end com GROMACS é identificado separadamente e não substitui revisão científica.

## Decisões E Revisões Humanas

- Esta proposta escolhe o exemplo smoke apenas como primeira prova da experiência de software. Um notebook científico representativo será uma tarefa independente, escolhida e validada com revisão humana.
- Para uma etapa futura de notebook científico/visualização, considerar `MDAnalysis` para leitura e análise de estruturas/trajetórias, `NGLView` para visualização molecular 3D interativa e `ipywidgets` para controles interativos. São candidatas, não dependências aprovadas; avaliar compatibilidade com JupyterLab e Conda/Micromamba, custo de instalação e limites de uso antes de adotá-las.
- As candidatas complementariam as figuras estáticas já produzidas pelo `gmxflow`; esta proposta não troca nem altera a análise científica existente.
- A pessoa revisora deve aprovar este percurso antes de se fixarem classes, métodos e estabilidade da API pública.
- Nenhuma conclusão sobre desempenho, qualidade de parâmetros ou validade científica pode ser derivada deste fluxo.

## Próxima Tarefa Após Aprovação

Adicionar testes de integração da API de execução com GROMACS em um ambiente reproduzível e, em seguida, construir o notebook smoke em cópia isolada do exemplo. A validação unitária da API não substitui esses testes: subprocessos continuam sendo usados internamente pelo executor compartilhado.
