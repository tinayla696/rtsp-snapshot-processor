FROM python:3.12-slim

WORKDIR /workspace

RUN apt-get update \
	&& apt-get install -y --no-install-recommends \
		ffmpeg \
		gstreamer1.0-libav \
		gstreamer1.0-plugins-bad \
		gstreamer1.0-plugins-good \
		gstreamer1.0-plugins-ugly \
		gstreamer1.0-tools \
	&& rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "src/stream_processor.py", "--help"]
