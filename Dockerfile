FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY . /app

# Run the dashboard as a non-root account. Uploaded projects are still arbitrary
# code; use isolated worker containers before exposing hosting to untrusted users.
RUN useradd --create-home --shell /usr/sbin/nologin appuser
USER appuser

EXPOSE 10000
CMD ["gunicorn", "app:app", "--workers", "1", "--threads", "8", "--timeout", "120", "--bind", "0.0.0.0:10000"]
