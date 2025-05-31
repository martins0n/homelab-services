import pytest
import pytest_asyncio # Not strictly needed for fixtures here, but good for consistency
import asyncio
from typing import List
import time # For unique chat_ids

# Assuming pytest is run from the root of the 'support-bot-py' project directory
from repository import Message, MessageRepository

# Use a unique chat ID for each test run to improve isolation
# One way is to use a timestamp
def generate_unique_chat_id() -> int:
    return int(time.time() * 1000)


@pytest.mark.asyncio
async def test_add_and_get_messages(message_repository: MessageRepository):
    test_chat_id = generate_unique_chat_id()

    messages_to_add: List[Message] = [
        Message(content="Hello there!", user="user"),
        Message(content="Hi, I am the assistant.", user="assistant"), # Corrected "I'm" to "I am"
    ]

    await message_repository.add_messages(test_chat_id, messages_to_add)

    retrieved_messages = await message_repository.get_messages(test_chat_id, limit=5)

    assert len(retrieved_messages) == 2, "Should retrieve two messages"
    assert retrieved_messages[0].content == "Hello there!"
    assert retrieved_messages[0].user == "user"
    assert retrieved_messages[1].content == "Hi, I am the assistant." # Corrected "I'm" to "I am"
    assert retrieved_messages[1].user == "assistant"

    # Test limit
    retrieved_one_message = await message_repository.get_messages(test_chat_id, limit=1)
    assert len(retrieved_one_message) == 1, "Should retrieve one message with limit=1"
    assert retrieved_one_message[0].content == "Hello there!"

    # Basic cleanup for this test_chat_id
    await asyncio.to_thread(
        message_repository.client.table("message").delete().eq("chat_id", test_chat_id).execute
    )

@pytest.mark.asyncio
async def test_get_messages_empty(message_repository: MessageRepository):
    non_existent_chat_id = generate_unique_chat_id() # Use a unique ID

    messages = await message_repository.get_messages(non_existent_chat_id)
    assert len(messages) == 0, "Should retrieve zero messages for a new chat_id"

@pytest.mark.asyncio
async def test_ping_repository(message_repository: MessageRepository):
    # The original ping returns data (list of dicts), not just a boolean.
    # This test ensures the query executes without error and returns a list.
    ping_result = await message_repository.ping()

    assert isinstance(ping_result, list), "Ping should return a list (data part of PostgrestResponse)"
    # If the database is empty, ping_result will be an empty list.
    # If there are messages, it will be a list with one item (the latest message's created_at).
