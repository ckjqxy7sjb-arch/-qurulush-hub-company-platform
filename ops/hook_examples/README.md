# Hook contract examples

These files show the JSON contract expected when `QH_REQUIRE_HOOK_JSON=1`.

They are examples, not production providers. Copy one into your private
integration repository or `/opt/qurulush/bin/`, replace the dry-run body with the
real provider/API call, and keep the JSON response shape.

Production deployment audit rejects env commands that reference `ops/hook_examples`
directly.

## Expected stdout

Each hook must exit with code `0` only after the external action is accepted and
print one JSON object to stdout:

```json
{"status":"synced","external_id":"REAL-ID-123","provider":"provider-name"}
```

Allowed statuses:

- sacc2: `ok`, `synced`
- EDS: `ok`, `signed`
- payments: `ok`, `confirmed`, `paid`
- storage: `ok`, `stored`, `uploaded`, `synced`
- AV scanner: `ok`, `clean`
- remote backup: `ok`, `stored`, `uploaded`, `synced`

On errors, return a non-zero exit code and write details to stderr.
