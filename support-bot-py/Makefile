get-webhook-info:
	curl https://api.telegram.org/bot${TOKEN}/getWebhookInfo

set-webhook:
	curl -F "url=${URL}" https://api.telegram.org/bot${TOKEN}/setWebhook

format:
	ruff check --select I --fix .

