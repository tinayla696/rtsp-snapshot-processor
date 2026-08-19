FROM python:3.12-slim

WORKDIR /workspace

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "src/stream_processor.py", "--help"]
