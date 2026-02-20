#!/bin/sh
# Substitute env vars in hooks.json, then start webhook
envsubst < /etc/webhook/hooks.json > /tmp/hooks.json
exec webhook -hooks /tmp/hooks.json -verbose -hotreload
