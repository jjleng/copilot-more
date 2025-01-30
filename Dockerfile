FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry and add to PATH
ENV POETRY_HOME=/opt/poetry
RUN curl -sSL https://install.python-poetry.org | python3 - && \
    cd /usr/local/bin && \
    ln -s /opt/poetry/bin/poetry && \
    poetry --version

# Copy poetry configuration files
COPY pyproject.toml poetry.lock ./

# Configure poetry to not create virtual environments inside containers
RUN poetry config virtualenvs.create false

# Install project dependencies
RUN poetry install --no-root --without dev

# Copy the rest of the application
COPY . .

# Install the project itself
RUN poetry install

EXPOSE 15432
