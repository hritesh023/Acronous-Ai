# Acronous VPS monitor — stdlib-only Python, internal use by dashboard.acronous.com.
FROM python:3.12-alpine
WORKDIR /app
COPY monitor.py ./
ENV PORT=9100
EXPOSE 9100
CMD ["python3", "monitor.py"]
