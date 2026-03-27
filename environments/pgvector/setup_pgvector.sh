#!/bin/bash

# PG vector setup for RAG
mkdir postgres_data
docker run --rm \
  -e POSTGRES_DB=codeindexerdb \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -d \
  --name deadend_pg \
  -p 54320:5432 \
  -v ./postgres_data:/var/lib/postgresql/data \
  pgvector/pgvector:pg17

