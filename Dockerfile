# syntax=docker/dockerfile:1
# Use --target review for video review/imports without the ML dependencies.
# Use --target cpu (the default) or --target gpu for tracking and family suggestions.
FROM node:26-bookworm-slim@sha256:298992629d69bbd5b2b03ad57094d8e4fcb3a8eeb7c4e25d29de656519568913 AS javascript

# Build tooling stays in this stage. Verify the committed asset snapshot so a
# wheel, source distribution and image all deliver the same reviewed UI bytes.
FROM javascript AS frontend
WORKDIR /build
COPY package.json package-lock.json .node-version ./
COPY backend/frontend/package.json ./backend/frontend/package.json
RUN npm ci --ignore-scripts
COPY backend/frontend ./backend/frontend
COPY backend/badminton/static ./backend/badminton/static
RUN npm run frontend:build && npm run frontend:stage:check

FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258 AS review
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    BADMINTON_ROOT=/state \
    BADMINTON_DATA_DIR=/state/data/processed \
    BADMINTON_WEIGHTS_DIR=/state/models/weights \
    HOME=/home/badminton \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_NO_CACHE=1 \
    PATH=/opt/venv/bin:$PATH

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        ca-certificates ffmpeg libatomic1 libgl1 libglib2.0-0 libstdc++6 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 badminton \
    && useradd --uid 10001 --gid 10001 --create-home --home-dir /home/badminton badminton \
    && mkdir -p /state/.media /state/data/processed /state/models/weights \
    && chown -R 10001:10001 /state

# Both images use Debian Bookworm/glibc; only the JS runtime is needed.
COPY --from=javascript /usr/local/bin/node /usr/local/bin/node
COPY --from=javascript /usr/local/LICENSE /usr/local/share/licenses/node/LICENSE
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY backend/badminton ./backend/badminton
COPY --from=frontend /build/backend/badminton/static ./backend/badminton/static
COPY scripts/download_models.py ./scripts/download_models.py
COPY docs ./docs
RUN /usr/local/bin/python -m pip install --no-cache-dir uv==0.9.4 \
    && uv sync --locked --no-dev --no-editable --extra youtube --extra download \
    && uv pip check --python /opt/venv/bin/python \
    && node --version \
    && ffmpeg -version

VOLUME ["/state"]
EXPOSE 8000
USER 10001:10001
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).read()"]
ENTRYPOINT ["badminton"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]

FROM review AS cpu
USER root
RUN uv sync --locked --no-dev --no-editable --extra youtube --extra download \
        --extra tracking --extra recognition --extra cpu \
    && uv pip check --python /opt/venv/bin/python \
    && python -c "import torch; from badminton.vendor.bst.bst import BST_0; assert torch.version.cuda is None; assert BST_0(in_dim=72, seq_len=30, n_class=35)(torch.zeros(1,30,2,72), torch.zeros(1,30,2), torch.tensor([30])).shape == (1,35)"
RUN python -c "from badminton.stroke_side import load_side_predictor; assert load_side_predictor('cpu') is not None"
USER 10001:10001

FROM review AS gpu
USER root
RUN uv sync --locked --no-dev --no-editable --extra youtube --extra download \
        --extra tracking --extra recognition --extra cuda \
    && uv pip check --python /opt/venv/bin/python \
    && python -c "import torch; assert torch.version.cuda == '12.6'"
USER 10001:10001

# Docker builds the last stage unless --target is supplied.
FROM cpu AS application
