const Router = class {
  routes: any[];
  defaultHandler: any;

  constructor() {
    this.routes = [];
  }

  addRoute(route: RegExp | string, handler) {
    this.routes.push({ route, handler });
  }

  getHandler(text: string) {
    const findRoute = this.routes.find(({ route }) => text.match(route));
    if (!findRoute) {
      return { route: null, handler: this.defaultHandler };
    }
    const { route, handler } = findRoute;
    return { route, handler };
  }

  async processUpdate(message) {
    const { text } = message;
    if (!text) return;
    const { route, handler } = this.getHandler(text);
    const content = text.match(route);
    console.log(route, content, text)
    if (route && content && content.length > 1) {
      await handler(message, content[1]);
    } else {
      await handler(message);
    }
  }
  
  addDefaultHandler(handler) {
    this.defaultHandler = handler;
  }
}

export default Router;