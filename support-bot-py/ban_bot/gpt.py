import asyncio

import httpx
from langchain.chains.llm import LLMChain
from langchain.chat_models import ChatOpenAI
from langchain_core.prompts import PromptTemplate

from settings import Settings

settings = Settings()

spam_examples = None


async def check_spam(text: str) -> bool:
    global spam_examples
    llm = ChatOpenAI(
        model_name=settings.model_spam,
        api_key=settings.openai_api_key,
    )
    
    if spam_examples is None:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(settings.spam_list)
            spam_examples = response.json()
    
    propmpt = PromptTemplate.from_template(
        """Examples of spam: {examples} \n
        You're given text to check if it spam \n
        Be sure to check if the text is spam or not. \n
        Text: {text} \n
        Return in the format: \n
        Reason: \n
        Verdict: Yes/No\n
        """,
        partial_variables={"examples": spam_examples}
    )
    
    chain = LLMChain(llm=llm, prompt=propmpt, verbose=True)
    
    answer = await chain.arun([text])
    
    verdict = answer.split("\n")[-1].split(":")[-1].strip()

    if verdict == "Yes":
        return True, answer
    else:
        return False, answer

if __name__ == "__main__":

    t = asyncio.run(check_spam("Привет, как дела?"))
    
    assert t[0] == False, t[1]
    
    t = asyncio.run(check_spam("Привет, как дела? Предалагаю вам купить курс по заработку на криптовалюте"))
    
    assert t[0] == True, t[1]