FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 仓库采集需要 git；ca-certificates 用于访问 HTTPS Git 仓库和 Qwen API。
RUN apt-get update \
    && apt-get install --no-install-recommends -y git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src ./src
RUN python -m pip install .

RUN mkdir -p /app/data/repositories

EXPOSE 8000

CMD ["uvicorn", "repopilot.main:app", "--host", "0.0.0.0", "--port", "8000"]
