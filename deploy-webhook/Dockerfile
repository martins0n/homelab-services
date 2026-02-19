FROM alpine:3.19
RUN apk add --no-cache docker-cli docker-cli-compose curl tar gettext
RUN curl -fsSL https://github.com/adnanh/webhook/releases/download/2.8.1/webhook-linux-arm64.tar.gz \
    | tar -xz -C /usr/local/bin --strip-components=1 webhook-linux-arm64/webhook
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
