FROM python:3.11-slim-buster@sha256:c46b0ae5728c2247b99903098ade3176a58e274d9c7d2efeaaab3e0621a53935

COPY requirements.txt requirements.txt

RUN pip install -r requirements.txt

COPY webserver.py webserver.py

EXPOSE 8000
USER 1005000:1005000

CMD ["python", "webserver.py"]