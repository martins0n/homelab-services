const TelegramBot = class {
  token: string;

  constructor(token) {
    this.token = token;
  }

  async sendMessage(chat_id, message) {

    const result = await fetch(`https://api.telegram.org/bot${this.token}/sendMessage`, {
      method: 'POST',
      body: JSON.stringify({
        chat_id,
        text: message,
      }),
      headers: {
        'Content-Type': 'application/json',
      }
    });
    const data = await result.json();
    console.log(`Sending message to  ${data}`);
  }
}

export default TelegramBot;