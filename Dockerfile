FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py skills.py quality.py pipeline.py design_systems.py browser_qa.py .
RUN mkdir -p /app/data/sites
CMD ["python", "app.py"]
