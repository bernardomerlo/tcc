# doc-as-code: ignore
#!/usr/bin/env python3
import argparse
import os
import sys
import glob
import re
from dotenv import load_dotenv

def load_project_env():
    """Carrega explicitamente o .env da pasta atual de execucao com override=True."""
    env_path = os.path.join(os.getcwd(), ".env")
    if os.path.exists(env_path):
        load_dotenv(dotenv_path=env_path, override=True)
        print(f"[CONFIG] .env carregado de: {env_path}")
    else:
        load_dotenv(override=True)
        print(f"[AVISO] Nenhum .env encontrado em {os.getcwd()}. Usando valores padrao.")

# Carrega na inicializacao
load_project_env()

from doc_as_code.ingestion_pipeline import run_ingestion_pipeline
from doc_as_code.tools import executar_git_local, buscar_rag_vetorial, ler_arquivo
from doc_as_code.llm_client import get_ollama_llm

def init_env():
    """Gera um arquivo .env de exemplo na raiz do projeto."""
    env_content = """# Configuracoes de IA do Doc-as-Code
OLLAMA_BASE_URL=http://localhost:11434
MODEL_NAME=llama3.1
EMBEDDING_MODEL=nomic-embed-text
LLM_TEMPERATURE=0.0

# Configuracoes do Projeto
DOCS_FOLDER=docs
SOURCE_FOLDER=
TARGET_EXTENSIONS=.py
"""
    env_path = os.path.join(os.getcwd(), ".env")
    if os.path.exists(env_path):
        print("O arquivo .env ja existe.")
    else:
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(env_content)
        print("Arquivo .env criado com as configuracoes padrao.")

def sync_docs():
    """Le a pasta de documentacao e atualiza o banco de dados vetorial."""
    load_project_env()
    docs_dir = os.getenv("DOCS_FOLDER", "docs")
    target_dir = os.path.join(os.getcwd(), docs_dir)
    print(f"[CONFIG] DOCS_FOLDER configurado: '{docs_dir}'")
    print(f"[CONFIG] Caminho de leitura: '{target_dir}'")
    run_ingestion_pipeline(docs_dir=target_dir)

def extrair_termos_chave(code_content: str) -> str:
    """Extrai entidades, classes e palavras-chave de ação para melhorar a busca no RAG."""
    palavras = re.findall(r'\b[A-Za-z_][A-Za-z0-9_]*\b', code_content)
    termos = []
    for p in palavras:
        if p in {"raise", "return", "except", "try", "yield"} or (p[0].isupper() and len(p) > 2):
            if p not in termos:
                termos.append(p)
    return " ".join(termos[:15])

def validate_chunk_with_llm(context_name: str, code_content: str, diff_content: str = None):
    """Envia o código para o LLM validar contra o RAG, com foco nas alterações (diff)."""
    print(f"\n[ANALISANDO] {context_name}")
    
    if "doc-as-code: ignore" in code_content.lower():
        print(f"[IGNORADO] Arquivo ignorado por regra de supressao.")
        return True
        
    # 1. Busca as regras no banco RAG combinando termos do diff e do código
    rag_k = int(os.getenv("RAG_K", "6"))
    base_text = diff_content if diff_content and diff_content.strip() else code_content
    termos_chave = extrair_termos_chave(base_text)
    query = f"{termos_chave} {base_text[:400]}"
    rag_context = buscar_rag_vetorial(query, k=rag_k)
    
    fontes = set()
    for linha in rag_context.split("\n"):
        if "Fonte:" in linha:
            fontes.add(linha.split("Fonte:")[-1].strip().rstrip(")-"))
    if fontes:
        print(f"[FONTES RAG]: {', '.join(os.path.basename(f) for f in fontes)}")
    
    # 2. Chama a IA
    model_name = os.getenv("MODEL_NAME", "llama3.1")
    temperature = float(os.getenv("LLM_TEMPERATURE", "0.0"))
    llm = get_ollama_llm(model_name=model_name, temperature=temperature)
    
    diff_section = f"\nALTERACOES RECENTES (GIT DIFF):\n{diff_content}\n" if diff_content and diff_content.strip() else ""
    
    prompt = f"""Você é um auditor rigoroso de código (Quality Gate de Arquitetura).
Sua ÚNICA tarefa é reprovar o código se ele violar qualquer regra do CONTEXTO RAG.
O CONTEXTO RAG é a lei absoluta. Seu conhecimento prévio sobre Python NÃO IMPORTA.

DIRETRIZES DE AUDITORIA:
1. FOQUE PRIMARIAMENTE NAS LINHAS MODIFICADAS OU ADICIONADAS (marcadas com '+').
2. AVALIAÇÃO ESTRITA:
   - Se o CONTEXTO RAG diz que você "não dá return, dá raise", e o código usa 'return HTTPException', isso é UMA VIOLAÇÃO DIRETA. Você DEVE responder FAILED.
   - NUNCA assuma que o contexto permite um erro. Se houver desvio, a decisão é FAILED.
3. DECISÃO BINÁRIA:
   - Se as alterações violarem regras documentadas no CONTEXTO RAG, responda FAILED. Se estiverem em conformidade, responda PASSED.

FORMATO OBRIGATÓRIO DE RESPOSTA:
DECISAO: [Escreva FAILED ou PASSED]
JUSTIFICATIVA: [Explicação técnica citando a regra exata do CONTEXTO RAG e a linha do código que falhou]

CONTEXTO RAG:
{rag_context}
{diff_section}
CÓDIGO COMPLETO PARA CONTEXTO ({context_name}):
{code_content}

Sua Resposta:"""

    try:
        resultado = llm.invoke(prompt)
        resposta_texto = resultado.content.strip()
        
        # Identifica a decisão de forma robusta
        is_failed = False
        for line in resposta_texto.split("\n")[:5]:
            line_upper = line.upper()
            if "DECISAO:" in line_upper or "DECISÃO:" in line_upper:
                if "FAILED" in line_upper:
                    is_failed = True
                break
            elif line_upper.startswith("FAILED"):
                is_failed = True
                break
                
        if not is_failed and "FAILED" in resposta_texto.upper()[:100]:
            is_failed = True
        
        if is_failed:
            print(f"[FALHA] Violação encontrada em {context_name}")
            print("-" * 50)
            print(resposta_texto)
            print("-" * 50)
            return False
        else:
            print(f"[PASSOU] {context_name} está em conformidade.")
            print("-" * 50)
            print(resposta_texto)
            print("-" * 50)
            return True
    except Exception as e:
        print(f"Erro ao consultar a IA: {e}")
        return False

def audit_codebase(audit_all=False):
    """Audita a base de código (git diff por padrão, ou todos os arquivos)."""
    load_project_env()
    extensions = os.getenv("TARGET_EXTENSIONS", ".py").split(",")
    source_folder = os.getenv("SOURCE_FOLDER", "").strip().rstrip("/\\")
    
    if audit_all:
        print(f"Iniciando varredura completa da codebase (pasta={source_folder or 'raiz'})...")
        all_passed = True
        
        # Encontra todos os arquivos com as extensões alvo
        for ext in extensions:
            pattern = f"{source_folder}/**/*{ext}" if source_folder else f"**/*{ext}"
            files = glob.glob(pattern, recursive=True)
            # Ignora pastas de ambiente virtual e cache
            files = [f for f in files if "venv/" not in f and "__pycache__" not in f and ".venv" not in f and "venv\\" not in f and ".venv\\" not in f]
            
            if not files:
                print(f"Nenhum arquivo encontrado para a extensão {ext} em '{source_folder or '.'}'.")
                continue
                
            for f_path in files:
                content = ler_arquivo(f_path)
                if not content.startswith("Erro:"):
                    passed = validate_chunk_with_llm(f_path, content)
                    if not passed:
                        all_passed = False
        
        if all_passed:
            print("\nAuditoria Completa: SUCESSO! Nenhum erro de arquitetura encontrado.")
            sys.exit(0)
        else:
            print("\nAuditoria Completa: FALHA! Foram encontradas violações nas regras de arquitetura.")
            sys.exit(1)
            
    else:
        # Padrão: Git Diff (Alterações pendentes ou recentes)
        print("Iniciando auditoria nas alterações recentes (git diff)...")
        diff_files_str = executar_git_local("diff --name-only")
        
        # Pega as alterações unstaged e staged
        diff_unstaged = executar_git_local("diff --name-only").strip()
        diff_staged = executar_git_local("diff --cached --name-only").strip()
        
        diff_files_str = "\n".join(filter(None, [diff_unstaged, diff_staged]))
            
        if not diff_files_str.strip():
            print("Nenhuma alteração encontrada para auditar. O repositório está limpo.")
            sys.exit(0)
            
        # Pega a lista unificada e remove duplicatas (caso um arquivo esteja em staged e unstaged)
        all_diff_files = list(set(f.strip() for f in diff_files_str.split('\n') if f.strip()))
        diff_files = [f for f in all_diff_files if any(f.endswith(ext) for ext in extensions)]
        
        # Filtra por SOURCE_FOLDER se configurado (ex: SOURCE_FOLDER=fastapi)
        if source_folder:
            diff_files = [
                f for f in diff_files 
                if f.replace('\\', '/').startswith(source_folder + '/') or f == source_folder
            ]
            print(f"[CONFIG] Filtrando alterações apenas na pasta '{source_folder}': {len(diff_files)} arquivo(s)")
            
        if not diff_files:
            print(f"Nenhuma alteração em arquivos com as extensões {extensions} na pasta alvo.")
            sys.exit(0)
            
        all_passed = True
        for f_path in diff_files:
            # Verifica se o arquivo ainda existe (pode ter sido deletado no diff)
            if not os.path.exists(f_path):
                continue
            content = ler_arquivo(f_path)
            
            # Pega o diff especifico deste arquivo (staged ou uncommitted)
            file_diff = executar_git_local(f"diff {f_path}")
            if not file_diff.strip():
                file_diff = executar_git_local(f"diff --cached {f_path}")
                
            if not content.startswith("Erro:"):
                passed = validate_chunk_with_llm(f_path, content, diff_content=file_diff)
                if not passed:
                    all_passed = False
                    
        if all_passed:
            print("\nAuditoria: SUCESSO! O código modificado está aderente às regras.")
            sys.exit(0)
        else:
            print("\nAuditoria: FALHA! O código modificado viola as regras de arquitetura.")
            sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Doc-as-Code CLI: Validação de Código via IA")
    subparsers = parser.add_subparsers(dest="command", help="Comandos disponíveis")
    
    # Comando init
    subparsers.add_parser("init", help="Inicializa o arquivo de configuração (.env)")
    
    # Comando sync
    subparsers.add_parser("sync", help="Lê a documentação e atualiza o banco vetorial (RAG)")
    
    # Comando audit
    audit_parser = subparsers.add_parser("audit", help="Audita o código fonte")
    audit_parser.add_argument("--all", action="store_true", help="Faz uma varredura completa em todos os arquivos da codebase em vez de usar apenas o diff")
    
    args = parser.parse_args()
    
    if args.command == "init":
        init_env()
    elif args.command == "sync":
        sync_docs()
    elif args.command == "audit":
        audit_codebase(audit_all=args.all)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
