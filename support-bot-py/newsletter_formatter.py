"""
Simple newsletter formatter
"""
from datetime import datetime


def format_newsletter(emails_by_sender: dict, days_back: int) -> str:
    """
    Create a simple newsletter with sender summaries
    """
    if not emails_by_sender:
        return "📰 Daily Newsletter\n\nNo new emails found."

    # Header
    total_emails = sum(len(emails) for emails in emails_by_sender.values())
    sender_count = len(emails_by_sender)
    current_date = datetime.now().strftime('%Y-%m-%d %H:%M')

    newsletter = f"""📰 Daily Newsletter
🕘 {current_date}
📊 {total_emails} emails from {sender_count} senders
📅 Last {days_back} day(s)

"""

    # Add each sender with full email address and placeholder for summary
    for sender, emails in emails_by_sender.items():
        # Extract just the email part if it's in format "Name <email@domain.com>"
        clean_sender = sender
        if '<' in sender and '>' in sender:
            clean_sender = sender.split('<')[1].split('>')[0]

        newsletter += f"📧 {clean_sender} ({len(emails)} emails):\n"
        newsletter += "SUMMARY_PLACEHOLDER\n\n"

    return newsletter


def format_newsletter_header(emails_by_sender: dict, days_back: int) -> str:
    """
    Create just the header part of the newsletter (Telegram HTML)
    """
    if not emails_by_sender:
        return "<b>📰 Daily Newsletter</b>\n\nNo new emails found."

    total_emails = sum(len(emails) for emails in emails_by_sender.values())
    sender_count = len(emails_by_sender)
    current_date = datetime.now().strftime('%Y-%m-%d %H:%M')

    return (
        f"<b>📰 Daily Newsletter</b>\n"
        f"🕘 {current_date}\n"
        f"📊 {total_emails} emails from {sender_count} senders\n"
        f"📅 Last {days_back} day(s)"
    )


def format_sender_message(sender: str, email_count: int, summary: str) -> str:
    """
    Format a single sender's summary as a standalone Telegram HTML message
    """
    clean_sender = sender
    if '<' in sender and '>' in sender:
        clean_sender = sender.split('<')[1].split('>')[0]

    return f"<b>📧 {clean_sender}</b> ({email_count} emails)\n\n{summary}"


def create_summary_prompt(sender: str, emails: list) -> str:
    """
    Create comprehensive content for AI to summarize with better context
    """
    content = f"Newsletter emails from {sender} (analyze for news content only):\n\n"
    
    for i, email in enumerate(emails[:10], 1):  # Increased to 10 emails for more context
        content += f"=== EMAIL {i} ===\n"
        content += f"Subject: {email.subject}\n"
        content += f"Date: {email.date.strftime('%Y-%m-%d %H:%M')}\n"
        content += f"Sender: {email.sender}\n"
        
        # Include more content - up to 1500 characters instead of 500
        email_body = email.body[:1500]
        if len(email.body) > 1500:
            email_body += "..."
        
        content += f"Content:\n{email_body}\n"
        
        # Include all extracted links for the AI to reference
        if email.links:
            content += f"Links: {', '.join(email.links[:5])}\n"
        
        content += "\n" + "="*50 + "\n\n"
    
    # Add instruction to focus on valuable content
    content += """
ANALYSIS INSTRUCTIONS:
- Summarize ALL informational and educational content, including technical blog posts
- Extract key insights, tutorials, technical developments, and industry updates  
- Include product updates, tool releases, and technical announcements
- For mixed content (educational + promotional), focus on the valuable information
- Consolidate related information from multiple emails
- Provide specific details like dates, numbers, companies, technologies, and facts
- Technical deep dives and blog posts should ALWAYS be included and summarized
- Only skip content that is purely promotional with zero educational value
"""
    
    return content