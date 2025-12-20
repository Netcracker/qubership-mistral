FROM python:3.7-slim-buster

# Copy and install requirements
COPY requirements.txt requirements.txt
RUN pip install --upgrade -r requirements.txt

# Copy your webserver code
COPY webserver.py webserver.py

# Expose port
EXPOSE 8000

# Run as non-root
USER 1005000:1005000

# Start server with Gunicorn (production-ready)
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:8000", "webserver:app"]