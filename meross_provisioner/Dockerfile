FROM ghcr.io/home-assistant/base-python:3.14-alpine3.24

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --disable-pip-version-check -r requirements.txt

COPY src/ ./src/
COPY run.sh ./run.sh
RUN chmod a+x ./run.sh

EXPOSE 8099
CMD ["/app/run.sh"]
