import { OpenAIApi, Configuration } from 'openai-edge';
import { MODEL } from '../config';

const configuration = new Configuration({
    apiKey: process.env.OPENAI_API_KEY,
});

const openai = new OpenAIApi(configuration);

const SIZE_LIMITS = {
    "gpt-3.5-turbo": 4096,
    "gpt-3.5-turbo-16k": 16384,  
}

export const filterMessagesContextSize = (messages: any[], contextSize = Math.floor(SIZE_LIMITS[MODEL] / 2)) => {
    let currentContextSize = 0;
    const arMessages = [...messages]
      .reverse()
      .map( (message) => ({...message, contentSize: currentContextSize += message.content.length}));
    const filteredMessages = arMessages
      .filter( (message) => message.contentSize < contextSize)
      .reverse()
      .map( (message) => ({content: message.content, role: message.role}));
    return filteredMessages;
}

export default openai;