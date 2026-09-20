# Arquitetura Interna do Projeto Doc-as-Code

Este documento define as regras arquiteturais obrigatórias para o desenvolvimento das ferramentas internas deste repositório. O objetivo é manter o código manutenível e padronizado.

## 1. Centralização do Cliente LLM

A fim de padronizar e facilitar a configuração da conexão com o modelo de inteligência artificial local (Ollama), definimos a seguinte restrição de arquitetura:

- **É ESTRITAMENTE PROIBIDO** instanciar as classes de conexão com o LLM (como `ChatOllama` da biblioteca `langchain_ollama` ou similares) diretamente nos scripts de regras de negócio, hooks ou agentes (arquivos na pasta `doc_as_code/` ou na raiz).
- **Regra de Ouro:** Toda e qualquer interação para criação do cliente de Inteligência Artificial deve ser feita **EXCLUSIVAMENTE** através da importação e uso da função `get_ollama_llm()` localizada no arquivo `doc_as_code/llm_client.py`.

**Exceções Absolutas (Não marcar FAILED nestes casos):**
1. O próprio arquivo `doc_as_code/llm_client.py` tem **autorização exclusiva** para importar a biblioteca e instanciar `ChatOllama`.
2. Modelos de Embeddings (como `OllamaEmbeddings`) **não** se enquadram nesta regra. Eles têm permissão total para serem importados e instanciados diretamente em arquivos de infraestrutura e pipelines (como `doc_as_code/tools.py` ou `doc_as_code/ingestion_pipeline.py`).

## 2. Padrão de Nomenclatura

Todos os scripts python devem seguir o padrão `snake_case`. Nenhuma classe deve ser definida sem o padrão `PascalCase`.

