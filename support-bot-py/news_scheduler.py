import asyncio
from datetime import datetime
from typing import Optional

from loguru import logger

from gmail_service import GmailService
from settings import Settings
from telegram import TelegramBot


class NewsScheduler:
    def __init__(self, telegram_bot: TelegramBot, settings: Settings):
        self.telegram_bot = telegram_bot
        self.settings = settings
        self.gmail_service = GmailService()
        self.is_running = False
        self._task: Optional[asyncio.Task] = None
        self._last_sent_date: Optional[str] = None

    async def start(self):
        """Start the news scheduler"""
        if self.is_running:
            logger.warning("News scheduler is already running")
            return
        
        if not self.settings.news_job_enabled:
            logger.info("News job is disabled in settings")
            return
        
        self.is_running = True
        self._task = asyncio.create_task(self._scheduler_loop())
        logger.info("News scheduler started")

    async def stop(self):
        """Stop the news scheduler"""
        if not self.is_running:
            return
        
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("News scheduler stopped")

    async def _scheduler_loop(self):
        """Main scheduler loop that runs continuously"""
        try:
            while self.is_running:
                await self._check_and_send_news()
                # Wait for 1 hour before checking again
                await asyncio.sleep(3600)  # 3600 seconds = 1 hour
        except asyncio.CancelledError:
            logger.info("News scheduler loop cancelled")
        except Exception as e:
            logger.error(f"Error in news scheduler loop: {e}")

    async def _check_and_send_news(self):
        """Check if it's time to send news to the configured channel"""
        current_time = datetime.now()
        current_hour = current_time.hour
        
        # Only check during the configured hour
        if current_hour != self.settings.news_job_hour:
            return
        
        # Check if channel is configured
        if not self.settings.news_channel_id:
            logger.warning("No news channel configured, skipping news delivery")
            return
        
        # Check if we already sent news today
        current_date = current_time.strftime("%Y-%m-%d")
        if self._last_sent_date == current_date:
            logger.info(f"News already sent today ({current_date})")
            return
        
        logger.info(f"Sending daily newsletter to channel {self.settings.news_channel_id}")
        
        try:
            await self._send_newsletter()
            self._last_sent_date = current_date
            logger.info("Daily newsletter sent successfully")
            
        except Exception as e:
            logger.error(f"Error sending daily newsletter: {e}")

    async def _send_newsletter(self):
        """Send newsletter to the configured channel"""
        channel_id = self.settings.news_channel_id
        
        try:
            logger.info(f"Generating newsletter for channel {channel_id}")
            
            # Fetch emails from the last N days
            emails = await self.gmail_service.fetch_emails_last_days(self.settings.news_default_days)
            
            if not emails:
                logger.info("No new emails found, skipping newsletter")
                return
            
            # Aggregate by sender
            sender_emails = self.gmail_service.aggregate_by_sender(emails)
            
            # Create newsletter (includes header and summary)
            newsletter = await self.gmail_service.create_news_summary(sender_emails)
            
            # Send newsletter (split if too long)
            if len(newsletter) > 4000:  # Telegram message limit
                chunks = [newsletter[i:i+4000] for i in range(0, len(newsletter), 4000)]
                for i, chunk in enumerate(chunks):
                    if i == 0:
                        await self.telegram_bot.send_message(channel_id, chunk)
                    else:
                        await self.telegram_bot.send_message(
                            channel_id, 
                            f"📰 Newsletter Continued...\n\n{chunk}"
                        )
            else:
                await self.telegram_bot.send_message(channel_id, newsletter)
            
            logger.info(f"Successfully sent newsletter to channel {channel_id}")
            
        except Exception as e:
            logger.error(f"Error sending newsletter to channel {channel_id}: {e}")
            raise

    async def send_test_newsletter(self) -> bool:
        """Send a test newsletter immediately (for testing)"""
        try:
            if not self.settings.news_channel_id:
                logger.error("No news channel configured")
                return False
            
            await self._send_newsletter()
            return True
            
        except Exception as e:
            logger.error(f"Error sending test newsletter: {e}")
            return False


async def main():
    """Main function for testing newsletter submission to channel"""
    logger.info("Starting newsletter test...")
    
    # Import settings and create telegram bot
    from settings import Settings
    from telegram import TelegramBot
    
    settings = Settings()
    
    # Check if channel is configured
    if not settings.news_channel_id:
        logger.error("NEWS_CHANNEL_ID not configured in environment variables")
        print("❌ Error: NEWS_CHANNEL_ID not configured")
        print("Please set NEWS_CHANNEL_ID in your .env file")
        print("Example: NEWS_CHANNEL_ID=-1001234567890")
        return
    
    if not settings.telegram_token:
        logger.error("TELEGRAM_TOKEN not configured")
        print("❌ Error: TELEGRAM_TOKEN not configured")
        return
    
    # Create components
    telegram_bot = TelegramBot(settings.telegram_token)
    scheduler = NewsScheduler(telegram_bot, settings)
    
    print(f"📰 Testing newsletter submission to channel: {settings.news_channel_id}")
    print(f"📅 Looking back {settings.news_default_days} day(s) for emails")
    print("🔄 Generating newsletter...")
    
    try:
        # Send test newsletter
        success = await scheduler.send_test_newsletter()
        
        if success:
            print("✅ Newsletter sent successfully!")
            print(f"📤 Check your channel: {settings.news_channel_id}")
        else:
            print("❌ Newsletter sending failed")
            print("Check the logs for more details")
            
    except Exception as e:
        logger.error(f"Error in main test function: {e}")
        print(f"❌ Error: {e}")
        print("Make sure:")
        print("1. Bot is added to the channel as admin")
        print("2. Gmail token is configured (GMAIL_TOKEN_BASE64 or token.pickle)")
        print("3. Channel ID is correct")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())