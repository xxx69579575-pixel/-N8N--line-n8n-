CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    file_name TEXT NOT NULL,
    file_ext TEXT NOT NULL,
    file_path TEXT NOT NULL,
    storage_type TEXT NOT NULL DEFAULT 'filesystem',
    mime_type TEXT,
    file_size BIGINT,
    source_folder TEXT,
    hash_sha256 TEXT NOT NULL UNIQUE,
    department TEXT,
    confidential_level TEXT DEFAULT 'internal',
    uploaded_by TEXT,
    created_time TIMESTAMPTZ,
    modified_time TIMESTAMPTZ,
    ingest_status TEXT NOT NULL DEFAULT 'pending',
    parse_status TEXT NOT NULL DEFAULT 'pending',
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_documents_hash_sha256 ON documents(hash_sha256);
CREATE INDEX IF NOT EXISTS idx_documents_department ON documents(department);
CREATE INDEX IF NOT EXISTS idx_documents_confidential_level ON documents(confidential_level);

CREATE TABLE IF NOT EXISTS document_contents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    full_text TEXT,
    text_source TEXT NOT NULL,
    language_code TEXT DEFAULT 'zh-TW',
    ocr_used BOOLEAN NOT NULL DEFAULT FALSE,
    page_count INTEGER,
    parse_status TEXT NOT NULL DEFAULT 'pending',
    parsed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_document_contents_document_id ON document_contents(document_id);

CREATE TABLE IF NOT EXISTS document_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    content_id UUID REFERENCES document_contents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    char_count INTEGER,
    token_estimate INTEGER,
    page_no INTEGER,
    sheet_name TEXT,
    section_title TEXT,
    embedding VECTOR(1024),
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_document_chunk UNIQUE (document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_document_chunks_document_id ON document_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_document_chunks_page_no ON document_chunks(page_no);
CREATE INDEX IF NOT EXISTS idx_document_chunks_sheet_name ON document_chunks(sheet_name);

CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding_cosine
ON document_chunks
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

CREATE TABLE IF NOT EXISTS document_permissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    department TEXT,
    role_name TEXT,
    access_level TEXT NOT NULL DEFAULT 'view',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_document_permissions_document_id ON document_permissions(document_id);
CREATE INDEX IF NOT EXISTS idx_document_permissions_role_name ON document_permissions(role_name);

CREATE TABLE IF NOT EXISTS processing_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE SET NULL,
    file_name TEXT,
    step_name TEXT NOT NULL,
    log_level TEXT NOT NULL DEFAULT 'info',
    message TEXT,
    details JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_processing_logs_document_id ON processing_logs(document_id);
CREATE INDEX IF NOT EXISTS idx_processing_logs_step_name ON processing_logs(step_name);

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_documents_updated_at ON documents;
CREATE TRIGGER trg_documents_updated_at
BEFORE UPDATE ON documents
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_document_contents_updated_at ON document_contents;
CREATE TRIGGER trg_document_contents_updated_at
BEFORE UPDATE ON document_contents
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_document_chunks_updated_at ON document_chunks;
CREATE TRIGGER trg_document_chunks_updated_at
BEFORE UPDATE ON document_chunks
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_document_permissions_updated_at ON document_permissions;
CREATE TRIGGER trg_document_permissions_updated_at
BEFORE UPDATE ON document_permissions
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE documents IS '文件主檔與 metadata';
COMMENT ON TABLE document_contents IS '抽出的全文內容與解析結果';
COMMENT ON TABLE document_chunks IS '切片內容與向量欄位';
COMMENT ON TABLE document_permissions IS '文件權限資訊';
COMMENT ON TABLE processing_logs IS '處理流程紀錄與錯誤追蹤';

