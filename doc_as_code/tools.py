# doc-as-code: ignore
import os
import subprocess
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings
from dotenv import load_dotenv

# Garante o carregamento das variáveis de ambiente
load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

def executar_git_local(comando: str, repo_path: str = ".") -> str:
    """
    Executa comandos Git localmente de forma segura e retorna a saída.
    
    Args:
        comando (str): O comando git a ser executado (ex: 'status', 'log -n 3', 'diff').
        repo_path (str): O diretório do repositório Git. Padrão é o diretório atual.
        
    Returns:
        str: Saída do comando em texto ou mensagem de erro formatada.
    """
    # Adiciona "git " caso o agente envie apenas o subcomando
    if not comando.strip().startswith("git "):
        comando = f"git {comando}"
        
    try:
        resultado = subprocess.run(
            comando,
            cwd=repo_path,
            shell=True,
            check=True,
            capture_output=True,
            text=True
        )
        return resultado.stdout.strip()
    except subprocess.CalledProcessError as e:
        return f"Erro ao executar git '{comando}':\nSaída de Erro: {e.stderr.strip()}"
    except Exception as e:
        return f"Erro inesperado na execução do git: {e}"

def buscar_rag_vetorial(query: str, k: int = 3, embedding_model: str = "nomic-embed-text") -> str:
    """
    Busca no banco de dados vetorial ChromaDB por trechos relevantes da documentação.
    
    Args:
        query (str): A pergunta ou termo de busca semântica.
        k (int): Número de documentos (chunks) a retornar.
        embedding_model (str): Nome do modelo de embeddings local a ser utilizado.
        
    Returns:
        str: Contexto consolidado com os trechos encontrados ou mensagem de erro.
    """
    try:
        db_path = os.getenv("CHROMA_PERSIST_DIRECTORY", os.path.join(os.getcwd(), ".chroma_db"))
        if not os.path.exists(db_path):
            return "Erro: Banco vetorial não encontrado. É necessário executar a ingestão (Fase 2) primeiro."
            
        embeddings = OllamaEmbeddings(
            model=embedding_model,
            base_url=OLLAMA_BASE_URL
        )
        
        # Conecta ao banco vetorial existente
        vector_store = Chroma(
            persist_directory=db_path,
            embedding_function=embeddings
        )
        
        # Realiza a busca por similaridade
        resultados = vector_store.similarity_search(query, k=k)
        
        if not resultados:
            return "Nenhum documento relevante encontrado para esta busca."
            
        contexto_formatado = []
        for i, doc in enumerate(resultados):
            fonte = doc.metadata.get("source", "Desconhecida")
            contexto_formatado.append(f"--- Trecho {i+1} (Fonte: {fonte}) ---\n{doc.page_content}\n")
            
        return "\n".join(contexto_formatado)
    except Exception as e:
        return f"Erro ao buscar no banco vetorial ChromaDB: {e}"

def ler_arquivo(caminho_arquivo: str) -> str:
    """
    Lê e retorna o conteúdo de um arquivo físico no repositório.
    
    Args:
        caminho_arquivo (str): Caminho absoluto ou relativo do arquivo.
        
    Returns:
        str: O conteúdo do arquivo como string ou mensagem de erro detalhada.
    """
    try:
        if not os.path.exists(caminho_arquivo):
            return f"Erro: O arquivo '{caminho_arquivo}' não foi encontrado."
            
        if not os.path.isfile(caminho_arquivo):
            return f"Erro: O caminho '{caminho_arquivo}' não aponta para um arquivo válido."
            
        with open(caminho_arquivo, 'r', encoding='utf-8') as f:
            return f.read()
            
    except UnicodeDecodeError:
        return f"Erro: Falha de decodificação. O arquivo '{caminho_arquivo}' pode não ser texto puro (UTF-8)."
    except PermissionError:
        return f"Erro: Permissão negada ao tentar ler '{caminho_arquivo}'."
    except Exception as e:
        return f"Erro inesperado ao ler o arquivo '{caminho_arquivo}': {e}"
