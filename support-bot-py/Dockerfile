FROM python:3.10-slim

WORKDIR /app

COPY . /app

RUN apt update && apt install -y gcc g++


RUN pip install --upgrade pip && \
    pip install poetry==1.6.1

RUN poetry config virtualenvs.create false

COPY pyproject.toml poetry.lock* /app/
RUN poetry install --no-dev


EXPOSE 8000

CMD ["poetry", "run", "fastapi", "run", "app.py"]