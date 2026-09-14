CREATE TABLE IF NOT EXISTS payments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  notification_id UUID REFERENCES notifications(id) ON DELETE SET NULL,
  object_id UUID REFERENCES construction_objects(id) ON DELETE SET NULL,
  title TEXT NOT NULL,
  basis TEXT,
  amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
  currency TEXT NOT NULL DEFAULT 'KGS',
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'checking', 'paid', 'appeal')),
  provider TEXT,
  payment_number TEXT,
  receipt_file_name TEXT,
  due_at DATE,
  paid_at TIMESTAMPTZ,
  paid_by UUID REFERENCES users(id) ON DELETE SET NULL,
  form_data JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_payments_company_status ON payments(company_id, status);
