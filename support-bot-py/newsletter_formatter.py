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


def create_summary_prompt(sender: str, emails: list) -> str:
    """
    Create content for AI to summarize
    """
    content = f"Emails from {sender}:\n\n"
    
    for i, email in enumerate(emails[:5], 1):  # Max 5 emails
        content += f"Email {i}:\n"
        content += f"Subject: {email.subject}\n"
        content += f"Content: {email.body[:500]}...\n"  # First 500 chars
        content += f"Date: {email.date.strftime('%Y-%m-%d')}\n\n"
    
    return content