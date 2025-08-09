#!/usr/bin/env python3
"""
Helper script to encode token.pickle as base64 for use in environment variables.
Usage: python encode_token.py
"""
import base64
import os

TOKEN_FILE = 'token.pickle'

def main():
    if not os.path.exists(TOKEN_FILE):
        print(f"❌ Error: {TOKEN_FILE} not found in current directory")
        print("Please make sure you have run goo.py to generate the token file first.")
        return
    
    try:
        with open(TOKEN_FILE, 'rb') as f:
            token_data = f.read()
        
        # Encode as base64
        encoded_token = base64.b64encode(token_data).decode('utf-8')
        
        print(f"✅ Successfully encoded {TOKEN_FILE}")
        print(f"📄 File size: {len(token_data)} bytes")
        print(f"📝 Base64 length: {len(encoded_token)} characters")
        print()
        print("🔧 Add this to your .env file:")
        print(f"GMAIL_TOKEN_BASE64={encoded_token}")
        print()
        print("💡 Or export as environment variable:")
        print(f"export GMAIL_TOKEN_BASE64='{encoded_token}'")
        
    except Exception as e:
        print(f"❌ Error encoding token: {e}")

if __name__ == "__main__":
    main()