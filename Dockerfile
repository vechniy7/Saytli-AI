FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py skills.py quality.py pipeline.py generation_repair.py design_systems.py browser_qa.py responsive_qa.py generation_validation.py contact_actions.py site_naming.py llm_stream.py visual_assets.py art_direction.py .
RUN mkdir -p /app/data/sites
CMD ["python", "app.py"]
