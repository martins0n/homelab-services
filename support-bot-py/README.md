# Support Bot Py

This project is a Python-based support bot.

## Running Tests

This project uses [pytest](https://docs.pytest.org/) for integration testing.

1.  **Install development dependencies**:
    If you haven't already, install all dependencies, including those required for testing. Ensure you are in the `support-bot-py` directory.
    ```bash
    poetry install --with dev
    ```

2.  **Ensure Test Environment Configuration**:
    The tests require a specific environment configuration file. Make sure you have `tests/.env.test` in the `support-bot-py/tests/` directory. This file contains test-specific environment variables. We created this file in an earlier step.

3.  **Run tests**:
    Navigate to the `support-bot-py` directory and run pytest:
    ```bash
    poetry run pytest
    ```
    This command will automatically discover and run the tests in the `tests/` directory.
