# --- Stage 1: build & patch ---
FROM alpine AS build
RUN apk add --no-cache unzip zip bash gawk sed
WORKDIR /work

COPY app.zip .
COPY configure-app.sh .
COPY patch-index.sh .
COPY about.md .

RUN chmod +x configure-app.sh patch-index.sh \
    # make configured ZIP
 && ./configure-app.sh app.zip "Telegram Channel Network Graph / Граф связей Telegram-каналов" about.md \
    # unzip it to /site for patching
 && mkdir /site \
 && unzip -q app-configured.zip -d /site \
    # patch index.html (title + meta + overlay)
 && ./patch-index.sh /site/index.html "Telegram Channel Network Graph / Граф связей Telegram-каналов" about.md

# --- Stage 2: serve ---
FROM nginx:alpine
COPY nginx.conf /etc/nginx/nginx.conf
COPY --from=build /site /usr/share/nginx/html
EXPOSE 8080
