# MUMO on Hugging Face Spaces (Docker SDK).
# micromamba base so the scientific stack (RDKit, AutoDock Vina, gemmi) installs
# from conda-forge as prebuilt binaries — nothing compiles at build time. HF free
# CPU gives 16 GB RAM, so the whole stack loads comfortably (vs Streamlit Cloud's
# ~1 GB, which OOM-restarted). Interaction profiling is ProLIF (Apache-2.0), not
# the GPL PLIP+OpenBabel it replaced — keeps MUMO patent-safe for commercial use.
FROM mambaorg/micromamba:latest

# --- conda deps first, so this layer caches across code-only changes ---
COPY --chown=mambauser:mambauser environment.yml /tmp/environment.yml
RUN micromamba install -y -n base -f /tmp/environment.yml && \
    micromamba clean --all --yes

# activate the base env for the remaining RUN/CMD steps
ARG MAMBA_DOCKERFILE_ACTIVATE=1

# belt-and-suspenders: guarantee the pip deps are present even if micromamba
# skipped the environment.yml pip subsection (idempotent if already installed)
RUN pip install --no-cache-dir streamlit meeko py3Dmol requests supabase dimorphite-dl \
    python-docx playwright prolif

# Playwright needs a real Chromium binary + OS-level libs (fonts, GTK, etc.) for
# headless screenshots — these back the .docx report's static 2D/3D/network
# images. --with-deps apt-installs those libs, which needs root — but the app
# itself runs as mambauser, and Playwright defaults to caching browsers under
# the INSTALLING user's home dir. Installing as root would put Chromium in
# /root/.cache (invisible to mambauser at runtime, silently breaking every
# screenshot). PLAYWRIGHT_BROWSERS_PATH pins it to one shared, readable spot.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
USER root
RUN mkdir -p /opt/ms-playwright && chmod -R 777 /opt/ms-playwright && \
    playwright install --with-deps chromium
USER mambauser

# ADMET-AI (TDC / Chemprop ML models for tox/CYP/PK). Install CPU-only PyTorch
# first from the CPU wheel index so we don't pull the multi-GB CUDA build, then
# admet-ai on top. Warm the model bundle at build time (bakes weights into the
# image → no slow download at runtime; also fails the build early if broken).
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir admet-ai && \
    python -c "from admet_ai import ADMETModel; ADMETModel(); print('admet-ai warmup OK')"

# Self-hosted BLAST database: download UniProt SwissProt (~90 MB gz) and format
# it into a local BLAST+ DB at /opt/blastdb/swissprot. blastp then runs in-
# container (seconds), so MUMO no longer depends on NCBI's web BLAST service
# (which is not licensed for production use). Placed after the torch layer so
# adding it doesn't invalidate that cache; the .fasta is deleted after formatting
# to keep the image lean (final DB ~250 MB). MUMO_BLAST_DB points blast_analyst here.
# Runs as root (/opt isn't writable by mambauser) and downloads via Python's
# urllib + gzip — the micromamba base image has no wget/gunzip.
ENV MUMO_BLAST_DB=/opt/blastdb/swissprot
USER root
RUN mkdir -p /opt/blastdb && cd /opt/blastdb && \
    python -c "import urllib.request, gzip, shutil; \
url='https://ftp.uniprot.org/pub/databases/uniprot/current_release/knowledgebase/complete/uniprot_sprot.fasta.gz'; \
urllib.request.urlretrieve(url, 'sprot.gz'); \
shutil.copyfileobj(gzip.open('sprot.gz','rb'), open('uniprot_sprot.fasta','wb'))" && \
    makeblastdb -in uniprot_sprot.fasta -dbtype prot -parse_seqids -out swissprot -title swissprot && \
    rm -f uniprot_sprot.fasta sprot.gz && chmod -R 755 /opt/blastdb
USER mambauser

# --- app code ---
WORKDIR /app
COPY --chown=mambauser:mambauser . /app

# HF Spaces routes external traffic to app_port (7860, set in README frontmatter)
ENV STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHERUSAGESTATS=false \
    STREAMLIT_SERVER_PORT=7860 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0
EXPOSE 7860

CMD ["streamlit", "run", "src/mumo_chat.py", \
     "--server.port=7860", "--server.address=0.0.0.0"]
