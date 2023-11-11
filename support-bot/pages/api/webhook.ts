import { TELEGRAM_TOKEN } from '../../config';
import Router from '../../router/router';
import openai from '../../lib/openai';
import { filterMessagesContextSize } from '../../lib/openai';
import messageRepository from '../../storage/messageRepository';
import { Message } from '../../storage/messageRepository';
import { TIMEOUT, SUMMARY_QUEUE_URL, YA_API, MODEL, X_TELEGRAM_BOT_HEADER } from '../../config'; 
import TelegramBot from '../../lib/telegram';

export const config = {
  runtime: 'edge'
}

const bot = new TelegramBot(TELEGRAM_TOKEN);
const router = new Router();

router.addRoute(/\/echo (.+)/, async (msg, matched) => {
  const { chat: { id } } = msg;
  await bot.sendMessage(id, `Received your message: ${matched}`);
});

router.addRoute(/\/start/, async (msg) => {
  const { chat: { id } } = msg;
  await bot.sendMessage(id, `Hello! I'm a bot. Send me a message and I'll echo it back to you.`);
});

router.addDefaultHandler(async (msg) => {
  const { chat: { id } } = msg;
  const messages = await messageRepository.getMessages(id, 100);
  console.log("messages getted");

  const new_message : Message = {
    content: msg.text as string,
    user: "user",
  }
  

  console.log(messages)

  const messagesToSend = filterMessagesContextSize([...messages.map(({ content, user }) => ({role: user, content})), { role: 'user', content: msg.text }]);
  const response = await openai.createChatCompletion({
    model: MODEL,
    messages: messagesToSend
  });
  const { choices } = await response.json();
    
  console.log(messagesToSend);

  const answer = choices[0].message;
  await bot.sendMessage(id, answer.content);
  console.log('message sent');
  await messageRepository.addMessages(id, [new_message])
  await messageRepository.addMessages(id, [{ content: answer.content, user: 'assistant' }])
  console.log('message added');
});

router.addRoute(/\/summary (.+)/, async (msg, matched) => {
  const { chat: { id } } = msg;
  const response = await openai.createChatCompletion({
    model: MODEL,
    messages: [
      {
        role: 'user',
        content: `Make a summary of the following text:\n\n${matched}\n\n`,
      }
    ]
  });
  const { choices } = await response.json();
  await bot.sendMessage(id, `Summary:\n\n${choices[0].message.content}`);
});

router.addRoute(/\/summary_url (.+)/, async (msg, matched) => {
  const { chat: { id } } = msg;

  console.log(matched);

  // extract url link from matched string
  const url = matched.match(/(https?:\/\/[^\s]+)/g)[0];
  await fetch(SUMMARY_QUEUE_URL, {
    method: 'POST',
    body: JSON.stringify({
      url: url,
      chat_id: id,
    }),
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Api-Key ${YA_API}`,
    }
  });
});

router.addRoute(/\/prompt (.+)/, async (msg, matched) => {
  const { chat: { id } } = msg;
  const response = await openai.createChatCompletion({
    model: MODEL,
    messages: [
      {
        role: 'user',
        content: `${matched}`,
      }
    ]
  });
  const { choices } = await response.json();
  await bot.sendMessage(id, `${choices[0].message.content}`);
});

const handler =  async (req) => {
  const body = await req.json();
  console.log(body);
  try {
    if (body.message) {
      await Promise.race([router.processUpdate(body.message), new Promise((resolve, reject) => {
        setTimeout(() => reject(new Error('request timeout')), TIMEOUT)
      })
    ]);
    }
  } catch (e) {
    console.error(e);
  }
}

export default async (req) => {
  // check header for telegram bot
  const xTelegramBotHeader = req.headers.get("X-Telegram-Bot-Api-Secret-Token");
  if (xTelegramBotHeader !== X_TELEGRAM_BOT_HEADER) {
      return new Response('Unauthorized', {
      status: 200,
      headers: { 'Content-Type': 'text/html; charset=utf-8' }
      });
  }
  const encoder = new TextEncoder();
 
  const readable = new ReadableStream({
    async start(controller) {
      controller.enqueue(
        encoder.encode(
          'ok',
        ),
      );
      await handler(req);
      controller.close();
    },
  });
 
  return new Response(readable, {
    headers: { 'Content-Type': 'text/html; charset=utf-8' },
  });
}