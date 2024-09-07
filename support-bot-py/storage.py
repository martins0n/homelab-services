from supabase import create_client

from settings import Settings

settings = Settings()
client = create_client(settings.database_url, settings.database_key)
