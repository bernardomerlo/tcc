from langchain_ollama import ChatOllama


def classificar_sentimento(texto):
    # Exemplo de violação arquitetural para teste da ferramenta:
    # Instanciação direta de ChatOllama em vez de usar doc_as_code.llm_client.get_ollama_llm()
    modelo_ai = ChatOllama(model="llama3.1", temperature=0.5)

    resposta = modelo_ai.invoke(f"Qual o sentimento deste texto: {texto}")
    return resposta.content
