# Inputs Do Exemplo Protein-Ligand Complex

Arquivos esperados neste diretório:

```text
3HTB.pdb
JZ4.pdb
JZ4.mol2
JZ4.str
```

`3HTB.pdb` e `JZ4.pdb` representam a estrutura inicial do receptor e a pose do ligante. `JZ4.mol2` e `JZ4.str` precisam ser compatíveis entre si e com `input.ligand_resname = "JZ4"` no `config.toml`.

O `gmxflow` não gera parâmetros CGenFF automaticamente. O arquivo `.str` deve ser obtido externamente por CGenFF/ParamChem/SilcsBio ou ferramenta equivalente.
