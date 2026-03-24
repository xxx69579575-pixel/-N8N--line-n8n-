CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  text TEXT,
  metadata JSONB,
  embedding VECTOR(768)
);