# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Formatting and Linting
- `ruff check --select I --fix .` - Format imports and fix issues
- Additional ruff commands available in pyproject.toml dev dependencies

### Telegram Bot Management
- `make get-webhook-info TOKEN=<token>` - Check current webhook configuration
- `make set-webhook URL=<webhook_url> TOKEN=<token> X_TELEGRAM_BOT_HEADER=<secret>` - Set webhook for Telegram bot

### Environment Setup
- Uses Poetry for dependency management: `poetry install`
- Python version: >=3.10,<3.14
- Environment variables defined in settings.py (uses .env file)

## Architecture Overview

This is a FastAPI-based Telegram bot with multiple features:

### Core Components
- **app.py**: Main FastAPI application with webhook handler and command routing
- **telegram.py**: TelegramBot class for sending messages via Telegram API
- **settings.py**: Pydantic settings with environment variable configuration
- **repository.py**: Message persistence using Supabase backend
- **schemas.py**: Pydantic models for Telegram webhook data

### Bot Features
1. **Chat Bot**: OpenAI-powered conversational AI with message history
2. **Content Summarization**: 
   - `/summary_url` - Summarize web articles using goose3
   - `/summary_youtube` - Summarize YouTube videos using transcript API
   - `/summary` - Summarize provided text
3. **Spam Detection**: Separate ban_bot module for spam filtering and user management
4. **Utility Commands**: `/echo`, `/prompt`, `/start`

### Key Dependencies
- FastAPI with async support
- OpenAI API for chat completions
- Supabase for message storage
- YouTube Transcript API and Google API client
- goose3 for web article extraction
- httpx for async HTTP requests

### Architecture Patterns
- Async/await throughout for non-blocking operations
- Command pattern for Telegram message handling
- Repository pattern for data access
- Settings injection via environment variables
- Modular routing with FastAPI routers (ban_bot module)

### Database Schema
- Messages stored with chat_id, content, user role, and created_at timestamp
- Supports conversation history retrieval with context size limits

### Gmail Integration
- Uses existing `token.pickle` file or `GMAIL_TOKEN_BASE64` environment variable
- Supports both file-based and base64-encoded token storage for containers
- Use `python encode_token.py` to convert token.pickle to base64 format
- Automatic token refresh handling

### Scheduled Jobs
- Background news scheduler runs continuously (configurable via `NEWS_JOB_ENABLED`)
- Default delivery time: 9 AM (configurable via `NEWS_JOB_HOUR`)
- User subscription management with database persistence

### Production Considerations
- Webhook verification using secret tokens
- Rate limiting in ban_bot module
- Environment-based dependency injection
- Health check endpoints at `/health` and `/api/health`
- Gmail token can be stored as base64 in environment variables for containers