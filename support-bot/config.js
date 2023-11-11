export const TELEGRAM_TOKEN = process.env.TELEGRAM_TOKEN;
export const DATABASE_URL = process.env.DATABASE_URL;
export const DATABASE_KEY = process.env.DATABASE_KEY;
export const TIMEOUT = parseInt(process.env.TIMEOUT, 10) || 20000;
export const SUMMARY_QUEUE_URL = process.env.SUMMARY_QUEUE_URL;
export const YA_API = process.env.YA_API;
export const MODEL = process.env.MODEL || 'gpt-3.5-turbo-16k';
export const X_TELEGRAM_BOT_HEADER = process.env.X_TELEGRAM_BOT_HEADER;