FROM python:3.12-slim

WORKDIR /app

# System deps:
#  - build-essential: for wheels with C extensions
#  - curl, ca-certificates, gnupg, lsb-release: for installing Azure CLI
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential curl ca-certificates gnupg lsb-release && \
    rm -rf /var/lib/apt/lists/*

# Install Azure CLI (needed by AzureCliCredential to fetch tokens).
# At runtime, mount the host's ~/.azure into the container so `az login`
# state is reused without re-authenticating inside the container.
RUN curl -sL https://aka.ms/InstallAzureCLIDeb | bash && \
    rm -rf /var/lib/apt/lists/*

# PII Shield mode: "api" (default) calls a remote service and needs no ML models.
# Set --build-arg PII_SHIELD_MODE=library to install pii-shield + spaCy + ONNX
# NER model in the image (~500MB extra) for in-process anonymization.
ARG PII_SHIELD_MODE=api
ENV PII_SHIELD_MODE=${PII_SHIELD_MODE}

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    if [ "$PII_SHIELD_MODE" = "library" ]; then \
        pip install --no-cache-dir "pii-shield>=0.2.0" && \
        python -m spacy download en_core_web_sm && \
        python -c "from optimum.onnxruntime import ORTModelForTokenClassification; from transformers import AutoTokenizer; ORTModelForTokenClassification.from_pretrained('protectai/bert-base-NER-onnx'); AutoTokenizer.from_pretrained('protectai/bert-base-NER-onnx'); print('ONNX model cached')"; \
    fi

COPY . .

# Install the local bankingbuddy package so `import bankingbuddy` works
RUN pip install --no-cache-dir -e .

EXPOSE 8501

CMD ["streamlit", "run", "app/streamlit_chat.py", \
     "--server.port", "8501", \
     "--server.address", "0.0.0.0", \
     "--server.headless", "true"]
