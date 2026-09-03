# V2.13.1 — Member Export Refinement

Adds Commissioner CSV exports without weakening password security.

**Export Member List CSV** includes display name, username, role, account status, linked pool identities, last login, and password status.

Existing private passwords cannot be exported because only secure one-way password hashes are stored.

Temporary credentials can be exported when they are issued during account creation, bulk creation, or a Commissioner reset. **Reset & Export Credential** resets one member to a new temporary password and immediately downloads that credential.

No Supabase migration is required.
