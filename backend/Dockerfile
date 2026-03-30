FROM python:3.12-slim

WORKDIR /app

# Install LibreOffice and necessary dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libreoffice-core \
        libreoffice-writer \
        libreoffice-calc \
        libreoffice-impress \
        libreoffice-common \
        fonts-dejavu \
        fonts-liberation && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \
    mkdir -p /app/.config/libreoffice && \
    ln -sf /usr/lib/libreoffice/program/soffice /usr/bin/soffice

# Install Git for mlflow
RUN apt-get update && \
    apt-get install -y git && \
    rm -rf /var/lib/apt/lists/* \

ENV PYTHONPATH=/usr/lib/libreoffice/program

COPY pyproject.toml /app/

RUN pip install poetry

RUN #pip install rpds

RUN poetry config virtualenvs.create false && poetry install --no-root

COPY . /app

EXPOSE 80

CMD ["poetry", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80"]
