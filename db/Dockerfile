# Postgres with q3c, the spherical indexing extension used for cone search.
FROM postgres:16-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-16-q3c \
    && rm -rf /var/lib/apt/lists/*
