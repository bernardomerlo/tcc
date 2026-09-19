# Regras de Arquitetura de Software
    
## Camada de Acesso a Dados (Banco de Dados)
1. É ESTRITAMENTE PROIBIDO utilizar a biblioteca `sqlite3` ou queries SQL cruas (raw queries) diretamente nos arquivos da pasta `src/`.
2. Todo acesso a banco de dados deve ser feito exclusivamente através do ORM padrão adotado pelo projeto (SQLAlchemy).
3. Qualquer código que importe `sqlite3` está violando as diretrizes de Doc-as-Code e deve ser sumariamente bloqueado.
