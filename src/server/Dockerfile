FROM python:3.12-slim
WORKDIR /app
COPY src/server/requirements.txt /app/src/server/requirements.txt
RUN pip install --no-cache-dir -r /app/src/server/requirements.txt
COPY src/server /app/src/server
COPY tools /app/tools
COPY src/micros_tooling /app/src/micros_tooling
ENV PYTHONPATH=/app/src
EXPOSE 8443
CMD ["python", "-u", "-m", "server.relay", "--state", "/state"]
