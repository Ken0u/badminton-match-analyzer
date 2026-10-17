# syntax=docker/dockerfile:1
# Use --target review for video review/imports without the ML dependencies.
# Use --target cpu (the default) or --target gpu for tracking and family suggestions.
FROM node:24-bookworm-slim AS javascript

FROM python:3.12-slim-bookworm AS review
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    BADMINTON_ROOT=/state \
    BADMINTON_DATA_DIR=/state/data/processed \
    BADMINTON_WEIGHTS_DIR=/state/models/weights \
    HOME=/home/badminton

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
COPY pyproject.toml README.md ./
COPY backend ./backend
COPY scripts/download_models.py ./scripts/download_models.py
COPY docs ./docs
RUN python -m pip install --no-cache-dir ".[youtube,download]" \
    && python -m pip check \
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
RUN python -m pip install --no-cache-dir \
        torch==2.8.0 torchvision==0.23.0 \
        --index-url https://download.pytorch.org/whl/cpu \
    && python -m pip install --no-cache-dir ".[tracking,recognition]" \
    && python -m pip check \
    && python -c "import torch; from badminton.vendor.bst.bst import BST_0; assert torch.version.cuda is None; assert BST_0(in_dim=72, seq_len=30, n_class=35)(torch.zeros(1,30,2,72), torch.zeros(1,30,2), torch.tensor([30])).shape == (1,35)"
USER 10001:10001

FROM review AS gpu
USER root
RUN python -m pip install --no-cache-dir \
        torch==2.8.0 torchvision==0.23.0 \
        --index-url https://download.pytorch.org/whl/cu126 \
    && python -m pip install --no-cache-dir ".[tracking,recognition]" \
    && python -m pip check \
    && python -c "import torch; assert torch.version.cuda == '12.6'"
USER 10001:10001

# Docker builds the last stage unless --target is supplied.
FROM cpu AS application
