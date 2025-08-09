import asyncio
import base64
import os
import pickle
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List

from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from loguru import logger
from openai import AsyncOpenAI

from settings import Settings

settings = Settings()


class GmailEmail:
    def __init__(self, sender: str, subject: str, body: str, date: datetime, message_id: str, links: List[str] = None):
        self.sender = sender
        self.subject = subject
        self.body = body
        self.date = date
        self.message_id = message_id
        self.links = links or []

    def __repr__(self):
        return f"GmailEmail(sender={self.sender}, subject={self.subject[:50]}...)"


class GmailService:
    TOKEN_FILE = 'token.pickle'
    
    def __init__(self):
        self.service = None
        self.openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    
    async def _authenticate(self):
        """Authenticate with Gmail API using token.pickle or base64 encoded token"""
        creds = None
        
        # First try to load from base64 encoded settings
        if settings.gmail_token_base64:
            try:
                logger.info("Loading Gmail token from base64 settings")
                token_data = base64.b64decode(settings.gmail_token_base64)
                creds = pickle.loads(token_data)
            except Exception as e:
                logger.error(f"Failed to load token from base64 settings: {e}")
        
        # Fallback to file-based token
        if not creds and os.path.exists(self.TOKEN_FILE):
            logger.info("Loading Gmail token from file")
            with open(self.TOKEN_FILE, 'rb') as token:
                creds = pickle.load(token)
        
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info("Refreshing expired Gmail token")
                creds.refresh(Request())
                
                # Save refreshed token to file if it exists
                if os.path.exists(self.TOKEN_FILE):
                    with open(self.TOKEN_FILE, 'wb') as token:
                        pickle.dump(creds, token)
                    logger.info("Saved refreshed token to file")
            else:
                raise Exception("Invalid Gmail credentials. Please run goo.py to authenticate or set gmail_token_base64 in settings.")
        
        self.service = build('gmail', 'v1', credentials=creds)
        logger.info("Gmail service authenticated successfully")

    async def fetch_emails_last_days(self, days: int = 7) -> List[GmailEmail]:
        """Fetch emails from the last N days"""
        if not self.service:
            await self._authenticate()
        
        # Calculate date N days ago
        date_filter = datetime.now() - timedelta(days=days)
        query = f"after:{date_filter.strftime('%Y/%m/%d')}"
        
        logger.info(f"Fetching emails from last {days} days with query: {query}")
        
        try:
            # Get messages list
            results = await asyncio.to_thread(
                self.service.users().messages().list,
                userId='me',
                q=query,
                maxResults=500
            )
            results = await asyncio.to_thread(results.execute)
            messages = results.get('messages', [])
            
            if not messages:
                logger.info("No messages found")
                return []
            
            logger.info(f"Found {len(messages)} messages, processing...")
            
            # Process each message
            emails = []
            for msg in messages:
                try:
                    email = await self._process_message(msg['id'])
                    if email:
                        emails.append(email)
                except Exception as e:
                    logger.error(f"Error processing message {msg['id']}: {e}")
                    continue
            
            logger.info(f"Successfully processed {len(emails)} emails")
            return emails
            
        except Exception as e:
            logger.error(f"Error fetching emails: {e}")
            return []

    async def _process_message(self, message_id: str) -> GmailEmail:
        """Process a single Gmail message"""
        try:
            message = await asyncio.to_thread(
                self.service.users().messages().get,
                userId='me',
                id=message_id
            )
            message = await asyncio.to_thread(message.execute)
            
            # Store current message for fallback access
            self._current_message = message
            
            payload = message['payload']
            headers = payload['headers']
            
            # Extract headers
            subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
            sender = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown Sender')
            date_str = next((h['value'] for h in headers if h['name'] == 'Date'), '')
            
            # Parse date
            try:
                # Gmail date format example: "Mon, 1 Jan 2024 12:00:00 +0000"
                date = datetime.strptime(date_str.split(' (')[0], '%a, %d %b %Y %H:%M:%S %z')
                date = date.replace(tzinfo=None)  # Remove timezone for simplicity
            except:
                date = datetime.now()
            
            # Extract body
            body = self._extract_body(payload)
            
            # Extract links from both subject and body
            all_text = f"{subject} {body}"
            links = self._extract_links(all_text)
            
            return GmailEmail(
                sender=sender,
                subject=subject,
                body=body,
                date=date,
                message_id=message_id,
                links=links
            )
            
        except Exception as e:
            logger.error(f"Error processing message {message_id}: {e}")
            return None

    def _extract_body(self, payload) -> str:
        """Extract text body from email payload with detailed debugging"""
        body = ""
        
        # Debug: Log email structure
        logger.info(f"Email structure - mimeType: {payload.get('mimeType')}")
        logger.info(f"Has parts: {'parts' in payload}")
        if 'parts' in payload:
            logger.info(f"Number of parts: {len(payload['parts'])}")
            for i, part in enumerate(payload['parts']):
                logger.info(f"Part {i}: mimeType={part.get('mimeType')}, has_body={bool(part.get('body'))}, has_data={'data' in part.get('body', {})}")
        
        def extract_from_part(part, level=0):
            """Recursively extract text from email parts"""
            nonlocal body
            indent = "  " * level
            
            mime_type = part.get('mimeType', 'unknown')
            logger.debug(f"{indent}Processing part: {mime_type}")
            
            if mime_type == 'text/plain' and 'data' in part.get('body', {}):
                try:
                    data = part['body']['data']
                    decoded = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                    logger.info(f"{indent}Extracted {len(decoded)} chars from text/plain")
                    body += decoded + "\n"
                except Exception as e:
                    logger.warning(f"{indent}Failed to decode text/plain part: {e}")
            
            elif mime_type == 'text/html' and 'data' in part.get('body', {}):
                try:
                    data = part['body']['data']
                    html_content = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                    logger.info(f"{indent}Found HTML content: {len(html_content)} chars")
                    
                    # Enhanced HTML to text conversion
                    import re
                    from html import unescape
                    
                    # Remove script and style elements
                    text_content = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
                    
                    # Convert common HTML elements to text
                    text_content = re.sub(r'<br[^>]*>', '\n', text_content, flags=re.IGNORECASE)
                    text_content = re.sub(r'<p[^>]*>', '\n\n', text_content, flags=re.IGNORECASE)
                    text_content = re.sub(r'</p>', '', text_content, flags=re.IGNORECASE)
                    text_content = re.sub(r'<div[^>]*>', '\n', text_content, flags=re.IGNORECASE)
                    text_content = re.sub(r'</div>', '', text_content, flags=re.IGNORECASE)
                    
                    # Remove all remaining HTML tags
                    text_content = re.sub(r'<[^>]+>', ' ', text_content)
                    
                    # Decode HTML entities
                    text_content = unescape(text_content)
                    
                    # Clean up whitespace
                    text_content = re.sub(r'\n\s*\n', '\n\n', text_content)  # Multiple newlines to double
                    text_content = re.sub(r'[ \t]+', ' ', text_content)  # Multiple spaces to single
                    
                    logger.info(f"{indent}Converted HTML to {len(text_content)} chars of text")
                    
                    # Only add HTML content if we don't have plain text yet
                    if not body.strip():
                        body += text_content + "\n"
                        
                except Exception as e:
                    logger.warning(f"{indent}Failed to decode text/html part: {e}")
            
            # Check for attachment data that might contain the actual content
            elif 'attachmentId' in part.get('body', {}):
                logger.info(f"{indent}Found attachment: {part.get('body', {}).get('attachmentId')}")
                # Note: We'd need to fetch attachment separately, skip for now
            
            # Handle nested parts
            if 'parts' in part:
                logger.debug(f"{indent}Processing {len(part['parts'])} nested parts")
                for nested_part in part['parts']:
                    extract_from_part(nested_part, level + 1)
        
        # Start extraction
        if 'parts' in payload:
            for part in payload['parts']:
                extract_from_part(part)
        else:
            extract_from_part(payload)
        
        # Clean up the extracted body
        body = body.strip()
        original_length = len(body)
        
        # If still empty or very short, try to get snippet from message metadata
        if len(body) < 100 and hasattr(self, '_current_message') and self._current_message:
            snippet = self._current_message.get('snippet', '')
            if snippet and len(snippet) > 20:
                logger.info(f"Using email snippet as fallback content: {len(snippet)} chars")
                body = snippet
        
        logger.info(f"Final extracted body length: {len(body)} chars (original: {original_length})")
        if len(body) < 200:
            logger.warning(f"Suspiciously short email content: {body[:100]}...")
        
        return body

    def _extract_links(self, text: str) -> List[str]:
        """Extract HTTP/HTTPS links from text"""
        import re
        
        # Pattern to match HTTP/HTTPS URLs
        url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+[^\s<>"{}|\\^`\[\].,;:!?]'
        links = re.findall(url_pattern, text, re.IGNORECASE)
        
        # Remove duplicates and sort
        unique_links = list(set(links))
        
        # Filter out common tracking/unsubscribe links
        filtered_links = []
        exclude_patterns = [
            'unsubscribe', 'tracking', 'pixel', 'beacon', 'analytics',
            'googletagmanager', 'facebook.com/tr', 'doubleclick.net',
            'google-analytics', 'utm_', 'mailchimp', 'constantcontact',
            'campaignmonitor', 'sendinblue'
        ]
        
        for link in unique_links:
            # Skip if link contains any exclude patterns
            if not any(pattern in link.lower() for pattern in exclude_patterns):
                # Skip very long URLs (likely tracking)
                if len(link) < 200:
                    filtered_links.append(link)
        
        return filtered_links[:10]  # Limit to 10 links per email

    def aggregate_by_sender(self, emails: List[GmailEmail]) -> Dict[str, List[GmailEmail]]:
        """Group emails by sender"""
        aggregated = defaultdict(list)
        
        for email in emails:
            # Clean sender email (extract just email part)
            sender_clean = email.sender
            if '<' in sender_clean and '>' in sender_clean:
                sender_clean = sender_clean.split('<')[1].split('>')[0]
            
            aggregated[sender_clean].append(email)
        
        logger.info(f"Aggregated emails from {len(aggregated)} unique senders")
        return dict(aggregated)

    async def create_news_summary(self, sender_emails: Dict[str, List[GmailEmail]]) -> str:
        """Create newsletter with AI summaries"""
        from newsletter_formatter import create_summary_prompt, format_newsletter
        
        # Create base newsletter with full email addresses and placeholders
        newsletter = format_newsletter(sender_emails, 1)
        
        # Replace each placeholder with AI summary
        for sender, emails in sender_emails.items():
            if not emails:
                continue
                
            logger.info(f"Creating summary for {sender} with {len(emails)} emails")
            
            try:
                # Create prompt for AI
                prompt_content = create_summary_prompt(sender, emails)
                
                # Get AI summary
                response = await self.openai_client.chat.completions.create(
                    model=settings.model_summarizer,
                    messages=[
                        {
                            "role": "system",
                            "content": "Summarize the key news from these emails as bullet points. Use • for each main point. Focus on the most important topics and information. Keep it concise with 3-5 bullet points maximum."
                        },
                        {
                            "role": "user", 
                            "content": prompt_content
                        }
                    ],
                    max_tokens=200
                )
                
                summary = response.choices[0].message.content.strip()
                
                # Replace first occurrence of placeholder with summary
                newsletter = newsletter.replace("SUMMARY_PLACEHOLDER", summary, 1)
                
            except Exception as e:
                logger.error(f"Error creating summary for {sender}: {e}")
                newsletter = newsletter.replace("SUMMARY_PLACEHOLDER", "Error generating summary", 1)
        
        return newsletter