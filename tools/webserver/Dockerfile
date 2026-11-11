FROM python:3.7-slim-buster@sha256:9bd2bfc822a533f99cbe6b1311d5bf0ff136f776ebac9b985407829f17278935

COPY requirements.txt requirements.txt

RUN pip install -r requirements.txt

COPY webserver.py webserver.py

EXPOSE 8000
USER 1005000:1005000

CMD ["python", "webserver.py"]