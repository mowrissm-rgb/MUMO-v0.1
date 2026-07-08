# MUMO on Hugging Face Spaces (Docker SDK).
# micromamba base so the scientific stack (RDKit, OpenBabel, AutoDock Vina,
# PLIP, gemmi) installs from conda-forge/bioconda as prebuilt binaries —
# nothing compiles at build time. HF free CPU gives 16 GB RAM, so the whole
# stack loads comfortably (vs Streamlit Cloud's ~1 GB, which OOM-restarted).
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
    python-docx playwright

# Playwright needs a real Chromium binary + OS-level libs (fonts, GTK, etc.) for
# headless screenshots — these back the .docx report's static 2D/3D/network
# images. --with-deps apt-installs those libs, which needs root.
USER root
RUN playwright install --with-deps chromium
USER mambauser

# ADMET-AI (TDC / Chemprop ML models for tox/CYP/PK). Install CPU-only PyTorch
# first from the CPU wheel index so we don't pull the multi-GB CUDA build, then
# admet-ai on top. Warm the model bundle at build time (bakes weights into the
# image → no slow download at runtime; also fails the build early if broken).
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir admet-ai && \
    python -c "from admet_ai import ADMETModel; ADMETModel(); print('admet-ai warmup OK')"

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
