import client from "./storage";


export interface Message {
  content: string;
  user: 'user' | 'assistant';
}

class messageRepository {
  connection;

  constructor() {
    this.connection = client
  }

  async addMessages(chat_id: number, messages : Message[]) {
    const data = await this.connection
      .from('message')
      .insert(
        messages.map(message => ({...message, chat_id}))
      )
    console.log(data);
  }

  async getMessages(chat_id: number, limit: number = 1000) : Promise<Message[]> {
    const {data, error } = await this.connection
      .from('message')
      .select('content, user')
      .eq('chat_id', chat_id)
      .limit(limit)
      .order('created_at', { ascending: false })
    data.reverse();
    return data;
  }
}

export default new messageRepository();