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
RUN pip install --no-cache-dir streamlit meeko py3Dmol requests supabase

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
