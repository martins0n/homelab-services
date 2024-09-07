get-webhook-info:
	curl https://api.telegram.org/bot${TOKEN}/getWebhookInfo

set-webhook:
	curl -F "url=${URL}" -F "secret_token=${X_TELEGRAM_BOT_HEADER}" https://api.telegram.org/bot${TOKEN}/setWebhook

format:
	ruff check --select I --fix .
