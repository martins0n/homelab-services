import goose3
from langchain.chains.combine_documents.stuff import StuffDocumentsChain
from langchain.chains.llm import LLMChain
from langchain.chains.summarize import load_summarize_chain
from langchain.chat_models import ChatOpenAI
from langchain.docstore.document import Document
from langchain.text_splitter import TokenTextSplitter
from langchain_core.prompts import PromptTemplate

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
    text_splitter = TokenTextSplitter(model_name=settings.model_summarizer)
    
    
    texts = text_splitter.split_text(text)


    docs = [Document(page_content=text) for text in texts]
    

    chain = load_summarize_chain(llm, chain_type="map_reduce", verbose=True)

    return chain.run(docs)

def make_summary_single_call(text):


    prompt_template = """Write top 5 key ideas and a concise summary of the following:
    "{text}"
    TOP 5 KEY IDEAS:
    CONCISE SUMMARY:"""
    
    prompt = PromptTemplate.from_template(prompt_template)

    llm = ChatOpenAI(temperature=0, model_name=settings.model_summarizer, api_key=settings.openai_api_key)
    llm_chain = LLMChain(llm=llm, prompt=prompt, verbose=True)

    stuff_chain = StuffDocumentsChain(llm_chain=llm_chain, document_variable_name="text")

    docs = [Document(page_content=text)]

    return stuff_chain.run(docs)

def summary_url(url):
    text = extract_text(url)
    text_summary = make_summary_single_call(text)
    return text_summary