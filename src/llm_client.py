# doc-as-code: ignore
import os
from langchain_ollama import ChatOllama
from dotenv import load_dotenv

# Carrega variáveis de ambiente (se o arquivo .env existir)
load_dotenv()

def get_ollama_llm(model_name: str = "llama3.1", temperature: float = 0.0) -> ChatOllama:
    """
    Inicializa e retorna o cliente do Ollama usando LangChain.
    O Ollama deve estar rodando localmente na porta padrão (11434).
    
    Args:
        model_name (str): Nome do modelo (ex: 'llama3', 'mistral').
        temperature (float): Temperatura para geração de texto (0.0 para mais determinístico).
        
    Returns:
        ChatOllama: Instância do cliente conectada ao Ollama local.
    """
    llm = ChatOllama(
        model=model_name,
        temperature=temperature,
        base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    )
    return llm

if __name__ == "__main__":
    # Teste rápido de configuração do cliente
    print("Inicializando o cliente Ollama local...")
    try:
        # Usa 'llama3' como padrão, mas pode ser 'mistral' se você preferir
        llm = get_ollama_llm(model_name="llama3")
        print(f"Cliente inicializado com sucesso usando o modelo: {llm.model}")
        print(f"Conectado à URL: {llm.base_url}")
    except Exception as e:
        print(f"Erro ao inicializar o cliente: {e}")
