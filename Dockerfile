FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN sed -i 's/\r$//' requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Копируем остальной код и чистим скрипт запуска
COPY . .
RUN sed -i 's/\r$//' entrypoint.sh
RUN chmod +x entrypoint.sh

CMD ["sh", "entrypoint.sh"]
