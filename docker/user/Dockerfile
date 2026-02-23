FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    fastapi \
    uvicorn \
    pyjwt \
    pydantic \
    email-validator \
    python-multipart \
    zstandard \
    jinja2

COPY main.py .
COPY templates/ templates/
COPY static/ static/

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "3600"]
