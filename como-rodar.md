# Doc-as-Code CLI

Bem-vindo à ferramenta de auditoria de código baseada em Inteligência Artificial e Retrieval-Augmented Generation (RAG).
Esta ferramenta garante que o código-fonte desenvolvido obedeça estritamente à documentação técnica do projeto.

## 1. Pré-requisitos

- Python 3.10+
- [Ollama](https://ollama.com/) instalado localmente ou hospedado na rede.
- Modelos recomendados já baixados no Ollama:
  ```bash
  ollama pull llama3.1
  ollama pull nomic-embed-text
  ```

## 2. Instalação

1. Clone este repositório.
2. Ative um ambiente virtual e instale as dependências:
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
3. Inicialize as configurações:
   ```bash
   python doc_as_code.py init
   ```
   _Isso criará um arquivo `.env` na raiz. Ajuste a URL do Ollama ou as pastas se necessário._

## 3. Como Usar

### Passo A: Ingestão de Documentos

Toda vez que a documentação técnica (na pasta `docs/`) for atualizada, você precisa sincronizar o banco vetorial:

```bash
python doc_as_code.py sync
```

### Passo B: Auditoria de Código

Para auditar o código que você acabou de alterar (usando `git diff`):

```bash
python doc_as_code.py audit
```

Para fazer uma varredura completa em todos os arquivos mapeados do projeto:

```bash
python doc_as_code.py audit --all
```
