import goose3
from langchain.chains.summarize import load_summarize_chain
from langchain.chat_models import ChatOpenAI
from langchain.docstore.document import Document
from langchain.text_splitter import TokenTextSplitter

from settings import Settings

settings = Settings()


def extract_text(url):
    g = goose3.Goose()
    article = g.extract(url)
    return article.cleaned_text

def make_summary(text: str) -> str:
    
    llm = ChatOpenAI(
        model_name=settings.model_summarizer,
        api_key=settings.openai_api_key,
    )
    text_splitter = TokenTextSplitter()
    
    
    texts = text_splitter.split_text(text)


    docs = [Document(page_content=text) for text in texts]
    

    chain = load_summarize_chain(llm, chain_type="map_reduce")

    return chain.run(docs)


def summary_url(url):
    text = extract_text(url)
    text_summary = make_summary(text)
    return text_summary
