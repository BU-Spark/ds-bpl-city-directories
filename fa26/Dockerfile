# Optional Linux/amd64 runner. Native macOS setup is validated separately.
FROM mambaorg/micromamba:2.3.3

COPY --chown=$MAMBA_USER:$MAMBA_USER fa26/environment.yml /tmp/environment.yml
RUN micromamba install --yes --name base --file /tmp/environment.yml --strict-channel-priority
RUN micromamba clean --all --yes

ARG MAMBA_DOCKERFILE_ACTIVATE=1
WORKDIR /app
COPY --chown=$MAMBA_USER:$MAMBA_USER fa26/pyproject.toml /app/fa26/pyproject.toml
COPY --chown=$MAMBA_USER:$MAMBA_USER fa26/src/ /app/fa26/src/
COPY --chown=$MAMBA_USER:$MAMBA_USER fa26/config/ /app/fa26/config/
COPY --chown=$MAMBA_USER:$MAMBA_USER fa26/manifests/ /app/fa26/manifests/
RUN python -m pip install --no-cache-dir /app/fa26

ENTRYPOINT ["/usr/local/bin/_entrypoint.sh", "bpl-ocr"]
CMD ["--help"]
