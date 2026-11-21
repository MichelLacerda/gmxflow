# Instruções do Projeto

## Tarefas e revisão humana

- Trate mudanças como unidades pequenas e revisáveis. Para objetivos amplos ou com várias fases, proponha uma sequência de tarefas independentes, com escopo, exclusões e critérios de aceite; não implemente todas as fases em um único bloco sem pedido explícito.
- Mantenha cada alteração focada em um resultado coerente. Não aproveite uma tarefa para antecipar etapas futuras ou misturar refatorações não necessárias.
- A pessoa que submete código — escrito manualmente ou com auxílio de IA — deve compreender integralmente a contribuição, conseguir explicar seu comportamento e limitações e verificar as evidências de teste.
- Ao concluir uma tarefa, resuma o comportamento alterado, os arquivos relevantes, os testes/verificações executados e qualquer limitação ou decisão pendente. Identifique explicitamente decisões científicas que exijam revisão humana.

## Integridade técnica e científica

- Use o código e os testes como autoridade para o comportamento implementado. O roadmap expressa intenção futura, não funcionalidade existente.
- Não altere silenciosamente force fields, protonação, parâmetros de simulação, métodos de análise ou a interpretação de resultados. Quando uma escolha afetar conclusões científicas e não estiver especificada, explicite a decisão necessária.
- Trate o perfil `smoke` como validação da integração do software, não como simulação cientificamente interpretável.
- Preserve entradas do usuário e dados existentes; não sobrescreva arquivos implicitamente.

Para convenções específicas do gmxflow, consulte a skill [gmxflow-project](.agents/skills/gmxflow-project.md).
