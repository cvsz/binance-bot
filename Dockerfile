FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
# fixed uid so the bind-mounted ./data can be owned by the same user on the host
RUN useradd -m -u 1000 bot && mkdir -p /app/data && chown bot:bot /app/data
COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt
COPY bot ./bot
COPY run.py .
USER bot
VOLUME ["/app/data"]
EXPOSE 8080
ENTRYPOINT ["python", "run.py"]
CMD ["paper"]
