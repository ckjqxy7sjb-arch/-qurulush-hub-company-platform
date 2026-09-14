CREATE TABLE IF NOT EXISTS construction_objects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  address TEXT,
  cadastral_number TEXT,
  current_stage TEXT,
  external_ref TEXT,
  form_data JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
  UNIQUE (company_id, external_ref)
);

CREATE INDEX IF NOT EXISTS idx_objects_company ON construction_objects(company_id);
