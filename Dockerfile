FROM python:3.12-slim
WORKDIR /app
RUN useradd -m bot
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot ./bot
COPY run.py .
USER bot
VOLUME ["/app/data"]
ENTRYPOINT ["python", "run.py"]
CMD ["paper"]
EXPOSE 8080
