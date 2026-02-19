#!/usr/bin/env python3
"""
Run this script once to authenticate with Google and generate token.pickle.
Then run encode_token.py to convert it for use in GMAIL_TOKEN_BASE64.
"""
import pickle

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
CREDENTIALS_FILE = 'credentials.json'
TOKEN_FILE = 'token.pickle'


def main():
    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
    creds = flow.run_local_server(port=0)

    with open(TOKEN_FILE, 'wb') as f:
        pickle.dump(creds, f)

    print(f"✅ Token saved to {TOKEN_FILE}")
    print("Now run: python encode_token.py")


if __name__ == '__main__':
    main()
