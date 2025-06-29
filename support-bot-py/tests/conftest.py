import os
import asyncio
import types
import pytest

# Ensure required environment variables exist before importing app
os.environ.setdefault("TELEGRAM_TOKEN", "test")
os.environ.setdefault("DATABASE_URL", "http://localhost")
os.environ.setdefault("DATABASE_KEY", "key")
os.environ.setdefault("SUMMARY_QUEUE_URL", "http://localhost")
os.environ.setdefault("YA_API", "key")
os.environ.setdefault("X_TELEGRAM_BOT_HEADER", "header")
os.environ.setdefault("OPENAI_API_KEY", "test")

import sys
import types

# provide minimal stubs for optional heavy dependencies used in the app
langchain = types.ModuleType("langchain")
chains = types.ModuleType("langchain.chains")
chains.llm = types.ModuleType("langchain.chains.llm")
chat_models = types.ModuleType("langchain.chat_models")
prompt_mod = types.ModuleType("langchain_core.prompts")
summarize_mod = types.ModuleType("langchain.chains.summarize")
combine_mod = types.ModuleType("langchain.chains.combine_documents")
combine_mod.stuff = types.ModuleType("langchain.chains.combine_documents.stuff")
docstore_mod = types.ModuleType("langchain.docstore.document")
text_split_mod = types.ModuleType("langchain.text_splitter")
langchain.chains = chains
langchain.chat_models = chat_models
sys.modules.setdefault("langchain", langchain)
sys.modules.setdefault("langchain.chains", chains)
sys.modules.setdefault("langchain.chains.llm", chains.llm)
sys.modules.setdefault("langchain.chat_models", chat_models)
sys.modules.setdefault("langchain_core.prompts", prompt_mod)
sys.modules.setdefault("langchain.chains.summarize", summarize_mod)
sys.modules.setdefault("langchain.chains.combine_documents", combine_mod)
sys.modules.setdefault("langchain.chains.combine_documents.stuff", combine_mod.stuff)
sys.modules.setdefault("langchain.docstore.document", docstore_mod)
sys.modules.setdefault("langchain.text_splitter", text_split_mod)
sys.modules.setdefault("tiktoken", types.ModuleType("tiktoken"))
sys.modules["tiktoken"].encoding_for_model = lambda model: types.SimpleNamespace(encode=lambda s: list(range(len(str(s)))))
supabase_mod = types.ModuleType("supabase")
supabase_mod.create_client = lambda url, key: types.SimpleNamespace(table=lambda name: types.SimpleNamespace(select=lambda *args, **kwargs: types.SimpleNamespace(eq=lambda *args, **kwargs: types.SimpleNamespace(order=lambda *args, **kwargs: types.SimpleNamespace(limit=lambda *a, **k: types.SimpleNamespace(execute=lambda: types.SimpleNamespace(data=[]))))), insert=lambda items: types.SimpleNamespace(execute=lambda: None)))
sys.modules.setdefault("supabase", supabase_mod)
sys.modules.setdefault("goose3", types.ModuleType("goose3"))
sys.modules["goose3"].Goose = lambda *a, **k: types.SimpleNamespace(extract=lambda url: types.SimpleNamespace(cleaned_text=""))
sys.modules.setdefault("youtube_transcript_api", types.ModuleType("youtube_transcript_api"))
sys.modules["youtube_transcript_api"].YouTubeTranscriptApi = types.SimpleNamespace(get_transcript=lambda *a, **k: [])

# minimal classes used by the application
class Dummy:
    def __init__(self, *args, **kwargs):
        pass

class Document:
    def __init__(self, page_content):
        self.page_content = page_content

docstore_mod.Document = Document

class TokenTextSplitter:
    def __init__(self, model_name):
        pass
    def split_text(self, text):
        return [text]

text_split_mod.TokenTextSplitter = TokenTextSplitter

class StuffDocumentsChain:
    def __init__(self, llm_chain, document_variable_name="text"):
        pass
    def run(self, docs):
        return "summary"

combine_mod.stuff.StuffDocumentsChain = StuffDocumentsChain

class LLMChain:
    def __init__(self, llm=None, prompt=None, verbose=False):
        pass
    async def arun(self, texts):
        return "result"
    def run(self, docs):
        return "result"

chains.llm.LLMChain = LLMChain

class ChatOpenAI:
    def __init__(self, *args, **kwargs):
        pass

chat_models.ChatOpenAI = ChatOpenAI

def load_summarize_chain(llm, chain_type="map_reduce", verbose=False):
    class Chain:
        def run(self, docs):
            return "summary"
    return Chain()

summarize_mod.load_summarize_chain = load_summarize_chain

class PromptTemplate:
    @classmethod
    def from_template(cls, template):
        return cls()

prompt_mod.PromptTemplate = PromptTemplate

import app as app_module
from repository import Message

# replace summarizer functions with lightweight stubs
import summarizer as summarizer_module
summarizer_module.summary_url = lambda url: "summary"

class InMemoryRepo:
    def __init__(self):
        self.storage: dict[int, list[Message]] = {}

    async def get_messages(self, chat_id: int, limit: int = 100):
        return self.storage.get(chat_id, [])

    async def add_messages(self, chat_id: int, messages: list[Message]):
        self.storage.setdefault(chat_id, []).extend([
            Message(**m) if isinstance(m, dict) else m for m in messages
        ])

    async def ping(self):
        return True

import pytest_asyncio

@pytest_asyncio.fixture()
async def test_app(monkeypatch):
    repo = InMemoryRepo()
    monkeypatch.setattr(app_module, "message_repository", repo)

    send_calls = []
    async def fake_send(chat_id: int, text: str):
        send_calls.append((chat_id, text))
    monkeypatch.setattr(app_module.telegram_bot, "send_message", fake_send)
    # avoid heavy dependency tiktoken by simplifying context filter
    monkeypatch.setattr(app_module, "filter_context_size", lambda m, c, model: m)

    async def fake_create(*args, **kwargs):
        class Choice:
            def __init__(self, content):
                self.message = types.SimpleNamespace(content=content)
        return types.SimpleNamespace(choices=[Choice("answer")])

    monkeypatch.setattr(app_module.openai.chat.completions, "create", fake_create)
    yield app_module.app, repo, send_calls
    await asyncio.sleep(0.01)
