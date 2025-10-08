FROM postgres:18

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends postgresql-18-pgvector; \
    rm -rf /var/lib/ap/lists/*