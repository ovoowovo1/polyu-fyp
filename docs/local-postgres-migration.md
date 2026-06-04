# Local PostgreSQL Migration

This project can run against Neon with `pg_search` or against a Windows local PostgreSQL database with native PostgreSQL full-text search.

## Windows Local Setup

1. Install `pgvector` into the local PostgreSQL installation so `CREATE EXTENSION vector` works. On Windows, run this from an Administrator Visual Studio x64 developer prompt:

```cmd
set "PGROOT=D:\PostgreSQL"
cd %TEMP%
git clone --branch v0.8.2 https://github.com/pgvector/pgvector.git
cd pgvector
nmake /F Makefile.win
nmake /F Makefile.win install
```
2. Set a temporary local password variable in PowerShell:

```powershell
$env:LOCAL_PGPASSWORD = "your-local-postgres-password"
```

If `.env` uses the app role, also set a temporary Neon owner/admin connection string for full RLS-protected data export:

```powershell
$env:NEON_DUMP_DSN = "postgresql://neondb_owner:your-neon-password@your-direct-host/neondb?sslmode=require"
```

The app role cannot export every row when RLS hides data from that role.

3. Run the migration from `backend/RAG_python-quiz`:

```powershell
.\scripts\migrate_neon_to_local.ps1
```

The script reads `PG_DSN` from `.env`, switches Neon from pooler to direct host for `pg_dump`, drops and recreates `polyu_fyp_local`, filters unsupported `pg_search` restore entries, and runs smoke checks for extensions, table counts, RLS policy counts, vector data, and PostgreSQL-native keyword retrieval.

For local app runs, point `PG_DSN` at `polyu_fyp_local` and set:

```dotenv
FULLTEXT_SEARCH_BACKEND=postgres
```

Use `FULLTEXT_SEARCH_BACKEND=pg_search` for Neon so existing BM25 behavior remains unchanged.
