# NSE Brand Risk Monitor — container for Hugging Face Spaces (Docker SDK), Cloud Run or any Docker host.
#   docker build -t brand-risk .
#   docker run -p 7860:7860 brand-risk      → http://localhost:7860
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0 \
    PORT=7860 \
    SENTIMENT=auto \
    REFRESH_MINUTES=60 \
    HF_HOME=/tmp/hf-home

WORKDIR /app

# CPU-only PyTorch keeps the image small; then the rest of the requirements
COPY backend/requirements*.txt backend/
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install -r backend/requirements.txt -r backend/requirements-api.txt -r backend/requirements-finbert.txt

COPY . .

# Bake FinBERT into the image so the app starts without a 440 MB download
RUN python -c "from transformers import AutoTokenizer, AutoModelForSequenceClassification as M; \
c='backend/models/finbert_cache'; AutoTokenizer.from_pretrained('ProsusAI/finbert', cache_dir=c); \
M.from_pretrained('ProsusAI/finbert', cache_dir=c)"

# Hugging Face runs containers as uid 1000; the app writes results under backend/
RUN useradd -m -u 1000 user && chown -R user:user /app
USER user

EXPOSE 7860
CMD ["python", "backend/api.py"]
