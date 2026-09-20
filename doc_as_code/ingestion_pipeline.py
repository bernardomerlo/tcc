# doc-as-code: ignore
import os
import glob
from dotenv import load_dotenv
from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings

# Carrega as variáveis de ambiente (se o arquivo .env existir)
load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

def get_local_embeddings(model_name: str = "nomic-embed-text") -> OllamaEmbeddings:
    """
    Inicializa e retorna o modelo de embeddings rodando localmente via Ollama.
    
    Args:
        model_name (str): Nome do modelo de embeddings. Recomenda-se 'nomic-embed-text' 
                          ou 'mxbai-embed-large' para performance e qualidade.
                          
    Returns:
        OllamaEmbeddings: Instância conectada ao modelo local.
    """
    embeddings = OllamaEmbeddings(
        model=model_name,
        base_url=OLLAMA_BASE_URL
    )
    return embeddings

def load_markdown_documents(docs_dir: str):
    """
    Varre o diretório especificado de forma recursiva em busca de arquivos de documentação (.md, .rst, .txt).
    Utiliza o TextLoader para carregar o conteúdo de cada arquivo.
    """
    if not os.path.exists(docs_dir):
        print(f"Diretório '{docs_dir}' não encontrado. Criando diretório vazio...")
        os.makedirs(docs_dir)
        return []
    
    docs = []
    doc_files = []
    for ext in ("*.md", "*.rst", "*.txt"):
        doc_files.extend(glob.glob(os.path.join(docs_dir, "**", ext), recursive=True))
    
    # Remove duplicados mantendo a ordem
    doc_files = list(dict.fromkeys(doc_files))
    
    for file_path in doc_files:
        try:
            loader = TextLoader(file_path, encoding='utf-8')
            docs.extend(loader.load())
            print(f"Arquivo carregado com sucesso: {file_path}")
        except Exception as e:
            print(f"Erro ao carregar o arquivo {file_path}: {e}")
            
    return docs

def split_documents(documents, chunk_size: int = 1000, chunk_overlap: int = 200):
    """
    Aplica o RecursiveCharacterTextSplitter nos documentos carregados para 
    gerar chunks de tamanho adequado para as buscas vetoriais.
    """
    if not documents:
        return []
        
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        # Mantém a integridade de parágrafos e frases na quebra do Markdown
        separators=["\n\n", "\n", r"(?<=\. )", " ", ""]
    )
    
    split_docs = text_splitter.split_documents(documents)
    print(f"Processamento concluído: {len(documents)} documento(s) dividido(s) em {len(split_docs)} chunks.")
    return split_docs

def run_ingestion_pipeline(docs_dir: str = None, embedding_model: str = "nomic-embed-text"):
    """
    Função orquestradora que executa o pipeline completo:
    1. Carrega os arquivos de documentação (.md, .rst)
    2. Divide os textos em Chunks
    3. Gera embeddings e popula o banco vetorial ChromaDB
    """
    if docs_dir is None:
        docs_dir = os.getenv("DOCS_FOLDER", "docs")
        
    print("="*50)
    print(f"Iniciando Pipeline de Ingestão (RAG)")
    print(f"Diretório de documentos: {docs_dir}")
    print("="*50)
    
    # 1. Carregamento
    documents = load_markdown_documents(docs_dir)
    if not documents:
        print("Pipeline abortado: Nenhum documento de texto (.md, .rst) encontrado para processar.")
        print("Adicione arquivos de regras na pasta correspondente e tente novamente.")
        return None
        
    # 2. Divisão (Split)
    split_docs = split_documents(documents)
    if not split_docs:
        print("Pipeline abortado: Nenhum chunk foi gerado a partir dos documentos.")
        return None

    # 3. Geração de Embeddings e Armazenamento Vetorial
    print(f"\nInicializando modelo de embeddings local ('{embedding_model}')...")
    embeddings = get_local_embeddings(model_name=embedding_model)
    
    db_path = os.getenv("CHROMA_PERSIST_DIRECTORY", os.path.join(os.getcwd(), ".chroma_db"))
    print(f"Gerando embeddings e populando o ChromaDB no diretório: {db_path}")
    
    batch_size = int(os.getenv("EMBEDDING_BATCH_SIZE", "100"))
    total_chunks = len(split_docs)
    total_batches = (total_chunks + batch_size - 1) // batch_size
    print(f"Gravando {total_chunks} chunks no ChromaDB em lotes de {batch_size}...")

    vector_store = Chroma(
        persist_directory=db_path,
        embedding_function=embeddings
    )
    try:
        vector_store.delete_collection()
        vector_store = Chroma(
            persist_directory=db_path,
            embedding_function=embeddings
        )
    except Exception:
        pass

    for i in range(0, total_chunks, batch_size):
        batch = split_docs[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        print(f"Processando lote {batch_num}/{total_batches} ({len(batch)} chunks)...")
        vector_store.add_documents(batch)

    print("\n[SUCESSO] Pipeline de ingestão concluído e dados gravados no banco vetorial local!")
    return vector_store

if __name__ == "__main__":
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    docs_folder_name = os.getenv("DOCS_FOLDER", "docs")
    docs_directory = os.path.join(project_root, docs_folder_name)
    
    run_ingestion_pipeline(docs_dir=docs_directory)
