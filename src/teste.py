from langchain_ollama import ChatOllama

def classificar_sentimento(texto):
    # Isso é uma violação grave de arquitetura!
    # O desenvolvedor está instanciando o modelo diretamente na regra de negócio.
    modelo_ai = ChatOllama(model="llama3.1", temperature=0.5)
    
    resposta = modelo_ai.invoke(f"Qual o sentimento deste texto: {texto}")
    return resposta.content