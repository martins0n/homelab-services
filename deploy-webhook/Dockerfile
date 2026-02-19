FROM alpine:3.19
RUN apk add --no-cache docker-cli docker-cli-compose curl tar
RUN curl -fsSL https://github.com/adnanh/webhook/releases/download/2.8.1/webhook-linux-arm64.tar.gz \
    | tar -xz -C /usr/local/bin --strip-components=1 webhook-linux-arm64/webhook
ENTRYPOINT ["webhook", "-hooks", "/etc/webhook/hooks.json", "-verbose", "-hotreload"]
