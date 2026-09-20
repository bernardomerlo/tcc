# doc-as-code: ignore
#!/usr/bin/env python3
import argparse
import os
import sys
import glob
from dotenv import load_dotenv

# Carrega configurações do .env se existir
load_dotenv()

from src.ingestion_pipeline import run_ingestion_pipeline
from src.tools import executar_git_local, buscar_rag_vetorial, ler_arquivo
from src.llm_client import get_ollama_llm

def init_env():
    """Gera um arquivo .env de exemplo na raiz do projeto."""
    env_content = """# Configurações de IA do Doc-as-Code
OLLAMA_BASE_URL=http://localhost:11434
MODEL_NAME=llama3.1
EMBEDDING_MODEL=nomic-embed-text
LLM_TEMPERATURE=0.0

# Configurações do Projeto
DOCS_FOLDER=docs
TARGET_EXTENSIONS=.py
"""
    env_path = os.path.join(os.getcwd(), ".env")
    if os.path.exists(env_path):
        print("O arquivo .env já existe.")
    else:
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(env_content)
        print("Arquivo .env criado com as configurações padrão.")

def sync_docs():
    """Lê a pasta de documentação e atualiza o banco de dados vetorial."""
    docs_dir = os.getenv("DOCS_FOLDER", "docs")
    target_dir = os.path.join(os.getcwd(), docs_dir)
    print(f"Sincronizando documentos da pasta '{target_dir}' com o ChromaDB...")
    run_ingestion_pipeline(docs_dir=target_dir)

def validate_chunk_with_llm(context_name: str, code_content: str):
    """Envia o código para o LLM validar contra o RAG."""
    print(f"\n🔍 Analisando: {context_name}")
    
    if "doc-as-code: ignore" in code_content.lower():
        print(f"⏭️ [IGNORADO] Arquivo ignorado por regra de supressão.")
        return True
        
    # 1. Busca as regras no banco RAG
    query = f"Verifique as regras para o seguinte código:\n{code_content[:1000]}"
    rag_context = buscar_rag_vetorial(query, k=3)
    
    # 2. Chama a IA
    model_name = os.getenv("MODEL_NAME", "llama3.1")
    temperature = float(os.getenv("LLM_TEMPERATURE", "0.0"))
    llm = get_ollama_llm(model_name=model_name, temperature=temperature)
    
    prompt = f"""Você é um auditor de código estrito (quality gate).
Sua função é verificar se o código analisado viola as regras de arquitetura documentadas no CONTEXTO RAG.

CONTEXTO RAG (Regras da Empresa):
{rag_context}

CÓDIGO ANALISADO:
{code_content}

INSTRUÇÕES:
- Analise se o código contém algo explicitamente proibido ou conflitante com o CONTEXTO RAG.
- Se violar as regras, responda iniciando com a palavra exata "FAILED", seguida por uma quebra de linha e a justificativa técnica.
- Se estiver de acordo ou não houver regras sobre ele, responda iniciando com a palavra exata "PASSED", seguida pela justificativa.

Sua Resposta:"""

    try:
        resultado = llm.invoke(prompt)
        resposta_texto = resultado.content.strip()
        
        if resposta_texto.upper().startswith("FAILED"):
            print(f"[FALHA] Violação encontrada em {context_name}")
            print("-" * 50)
            print(resposta_texto)
            print("-" * 50)
            return False
        else:
            print(f"[PASSOU] {context_name} está em conformidade.")
            return True
    except Exception as e:
        print(f"Erro ao consultar a IA: {e}")
        return False

def audit_codebase(audit_all=False):
    """Audita a base de código (git diff por padrão, ou todos os arquivos)."""
    extensions = os.getenv("TARGET_EXTENSIONS", ".py").split(",")
    
    if audit_all:
        print("Iniciando varredura completa da codebase...")
        all_passed = True
        
        # Encontra todos os arquivos com as extensões alvo
        for ext in extensions:
            # Usar glob recursivo para pegar todos os arquivos
            files = glob.glob(f"**/*{ext}", recursive=True)
            # Ignora pastas de ambiente virtual e cache
            files = [f for f in files if "venv/" not in f and "__pycache__" not in f and ".venv" not in f]
            
            if not files:
                print(f"Nenhum arquivo encontrado para a extensão {ext}.")
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
        
        # Se não houver diff não commitado, pega o staged
        if not diff_files_str.strip():
            diff_files_str = executar_git_local("diff --cached --name-only")
            
        if not diff_files_str.strip():
            print("Nenhuma alteração encontrada para auditar. O repositório está limpo.")
            sys.exit(0)
            
        diff_files = [f for f in diff_files_str.split('\n') if f.strip() and any(f.endswith(ext) for ext in extensions)]
        
        if not diff_files:
            print(f"Nenhuma alteração em arquivos com as extensões {extensions}.")
            sys.exit(0)
            
        all_passed = True
        for f_path in diff_files:
            # Verifica se o arquivo ainda existe (pode ter sido deletado no diff)
            if not os.path.exists(f_path):
                continue
            content = ler_arquivo(f_path)
            if not content.startswith("Erro:"):
                passed = validate_chunk_with_llm(f_path, content)
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
