# Validador local de PRs (código × documentação)

Quando um dev abre ou atualiza um PR para a `main`, um runner self-hosted avisa este servidor local. O servidor busca o diff e a
documentação via `gh`, pede para uma IA local (Ollama) comparar os dois e mostra o relatório em um dashboard. O chefe aprova ou
pede mudanças com um clique (`gh pr review`).

```
PR → Runner self-hosted → POST /api/webhook/pr (202) → fila + SQLite → worker (gh + Ollama) → dashboard → gh pr review
```

## Passo a passo de uso

Tudo abaixo é feito **na máquina do chefe**, com o usuário do Windows que vai rodar o servidor.

### 1. Instalar as ferramentas
- [Python 3.10+](https://www.python.org/downloads/) e [Git](https://git-scm.com/)
- [GitHub CLI](https://cli.github.com/)
- [Ollama](https://ollama.com/)

### 2. Autenticar o GitHub CLI
```powershell
gh auth login      # GitHub.com → HTTPS → login pelo navegador, com a conta do chefe
gh auth status     # deve mostrar "Logged in"
```
A conta precisa poder ler e aprovar PRs do repositório. O `gh` autenticado é do usuário do Windows: o servidor deve rodar com esse mesmo usuário.

### 3. Baixar o modelo da IA
```powershell
ollama pull llama3.1:8b        # ou qwen2.5-coder
```
O `num_ctx` (32768 por padrão) é enviado em cada requisição, mas esse contexto consome bastante RAM/VRAM. Se a máquina sofrer, reduza `PR_NUM_CTX` no `.env`.

### 4. Instalar o validador
```powershell
cd <pasta deste projeto>
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```
Gere um segredo e cole em `PR_VALIDATOR_WEBHOOK_SECRET` no `.env`:
```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 5. Cadastrar o mesmo segredo no GitHub
No repositório que será monitorado: **Settings → Secrets and variables → Actions → New repository secret**
- Nome: `PR_VALIDATOR_WEBHOOK_SECRET`
- Valor: o mesmo do `.env`

### 6. Instalar o runner self-hosted
No repositório: **Settings → Actions → Runners → New self-hosted runner** (Windows). Siga os comandos mostrados na página
(`Invoke-WebRequest`, `config.cmd --url ... --token ...`). Quando perguntar *"run as service?"*, responda **Y**.
Confirme que o runner aparece como **Idle** (verde) na página.

### 7. Travar forks
**Settings → Actions → General → Fork pull request workflows from outside collaborators** → *Require approval for all outside collaborators*.
Prefira repositório privado. (O workflow já ignora PRs vindos de forks.)

### 8. Colocar o workflow no repositório monitorado
Copie [`.github/workflows/pr-validator.yml`](.github/workflows/pr-validator.yml) para o **mesmo caminho** no repositório monitorado e faça commit na `main`.
Se o monitorado for este próprio repositório, basta commitar e dar push.

### 9. Subir o servidor
```powershell
.\venv\Scripts\Activate.ps1
python -m pr_validator
```
Abra **http://localhost:5000**. O servidor precisa estar rodando sempre que houver PRs (para iniciar com o Windows, crie uma
tarefa no *Agendador de Tarefas* → "Ao fazer logon" → `venv\Scripts\python.exe -m pr_validator`, com "Iniciar em" = pasta do projeto).
Se ele estiver fora do ar quando o PR chegar, o job do workflow falha em vermelho e o PR não entra na fila: reexecute o job depois (*Re-run jobs*).

### 10. Rotina do chefe
1. O dev abre (ou dá push em) um PR para a `main`; o workflow roda no runner e o PR aparece no dashboard como **IA processando**.
2. Quando o badge virar **Válido** (verde) ou **Inconsistente** (vermelho), abra o card: resumo, pontos de doc/código não atualizados, inconsistências e o diff bruto.
3. Revise o comentário (já vem preenchido com os apontamentos da IA) e clique em **Aprovar PR** ou **Reprovar / Pedir ajuste**. O motivo é obrigatório ao reprovar.
4. Se um novo push chegar no mesmo PR, ele é revalidado automaticamente para o novo commit.
5. Card em **Erro**: leia a mensagem e clique em **Reprocessar** depois de corrigir (ex.: Ollama desligado).

> A IA é um apoio, não substitui a revisão: ela só compara o que está na documentação com o diff. Se o repositório não tiver `.md` em `docs/` ou um `README.md`, aparece um aviso de que o veredito é pouco confiável.

## Configuração (`.env`)

| Variável | Padrão | Descrição |
|---|---|---|
| `PR_VALIDATOR_HOST` / `PR_VALIDATOR_PORT` | `127.0.0.1` / `5000` | Endereço do servidor (o dashboard não tem login: mantenha local) |
| `PR_VALIDATOR_DB` | `data/pr_validator.sqlite3` | Banco SQLite |
| `PR_VALIDATOR_WEBHOOK_SECRET` | vazio | Segredo esperado no header `X-Webhook-Secret` |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | URL do Ollama |
| `PR_MODEL_NAME` | `llama3.1:8b` | Modelo da validação |
| `PR_NUM_CTX` | `32768` | Janela de contexto (`options.num_ctx`) |
| `PR_OUTPUT_RESERVE_TOKENS` | `2048` | Tokens reservados para a resposta |
| `PR_OLLAMA_TIMEOUT` / `PR_GH_TIMEOUT` | `900` / `120` | Timeouts (segundos) |
| `PR_DOCS_PATHS` | `docs/,README.md` | Prefixos (terminam em `/`) ou arquivos tratados como documentação |
| `PR_DOC_EXTENSIONS` | `.md,.mdx,.rst,.txt` | Extensões de documentação |
| `PR_DIFF_IGNORE_EXTRA` | vazio | Padrões glob extras a remover do diff |

## Comportamentos importantes
- **Status**: `PENDING` → `PROCESSING` → `WAITING_APPROVAL` → `APPROVED`/`REJECTED`; falhas viram `ERROR`.
- **Documentação**: lida da branch base via `gh api` (sem clone); docs alterados no PR entram na versão do PR.
- **Filtro de ruído**: lockfiles, `*.Designer.cs`, `*ModelSnapshot.cs`, `Migrations/*.cs`, `*.min.*`, binários, imagens/SVG. Os ignorados aparecem no relatório.
- **Contexto**: a documentação nunca é cortada. Diff grande demais tem os arquivos excedentes omitidos com aviso explícito; se a documentação sozinha não couber (ou o Ollama indicar truncamento), o PR vai para `ERROR`.
- **`isValid`** só é `true` se a IA disser que sim **e** as listas de problemas estiverem vazias.
- `gh pr review --approve` falha se o chefe for o autor do PR (o erro aparece no dashboard).

## Testes
```powershell
python -m unittest discover -s tests -t .
```

