# MUMO Specialist A — docking & structure.
#
# Serves HTTP on 7860 (src/services/space_a.py), running each dock in a
# subprocess so a Vina segfault kills a child rather than this service.
FROM mambaorg/micromamba:latest

COPY --chown=$MAMBA_USER:$MAMBA_USER deploy/space-a/environment.yml /tmp/environment.yml
RUN micromamba install -y -n base -f /tmp/environment.yml && \
    micromamba clean --all --yes
ARG MAMBA_DOCKERFILE_ACTIVATE=1

# belt-and-braces, matching the main image: guarantee the pip deps landed
RUN pip install --no-cache-dir meeko prolif requests supabase

WORKDIR /app
COPY --chown=$MAMBA_USER:$MAMBA_USER src/ /app/src/

ENV PYTHONPATH=/app/src
ENV PORT=7860
EXPOSE 7860

# no --server flags: this is a plain HTTP service, not Streamlit
CMD ["python", "/app/src/services/space_a.py"]
