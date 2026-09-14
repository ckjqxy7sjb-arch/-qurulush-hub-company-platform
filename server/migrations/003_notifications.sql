CREATE TABLE IF NOT EXISTS notifications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  object_id UUID REFERENCES construction_objects(id) ON DELETE SET NULL,
  source TEXT NOT NULL,
  source_ref TEXT,
  type TEXT NOT NULL CHECK (type IN ('request', 'payment', 'remark', 'inspection', 'status', 'document')),
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'needs_company', 'in_work', 'sent', 'closed')),
  urgent BOOLEAN NOT NULL DEFAULT false,
  assignee_id UUID REFERENCES users(id) ON DELETE SET NULL,
  due_at DATE,
  accepted_at TIMESTAMPTZ,
  sent_at TIMESTAMPTZ,
  reply_text TEXT,
  form_data JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
  UNIQUE (company_id, source_ref)
);

CREATE INDEX IF NOT EXISTS idx_notifications_company_status ON notifications(company_id, status);
CREATE INDEX IF NOT EXISTS idx_notifications_due ON notifications(due_at);
