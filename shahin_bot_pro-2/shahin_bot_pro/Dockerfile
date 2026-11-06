FROM python:3.11-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DB_PATH=/app/data/alias_group.db
ENV WEB_HOST=0.0.0.0
ENV WEB_PORT=8080

RUN mkdir -p /app/data
COPY requirements-prod.txt /app/requirements-prod.txt
RUN pip install --no-cache-dir -r /app/requirements-prod.txt

COPY bot.py config.py database.py security.py utils.py main.py webapp.py bot_runtime.py envutil.py /app/

EXPOSE 8080
CMD ["python", "main.py"]
