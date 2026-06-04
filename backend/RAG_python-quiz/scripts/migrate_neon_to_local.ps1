param(
    [string]$EnvPath = ".\.env",
    [string]$PgBin = "D:\PostgreSQL\bin",
    [string]$LocalDbName = "polyu_fyp_local",
    [string]$LocalHostName = "localhost",
    [int]$LocalPort = 5432,
    [string]$LocalUser = "postgres",
    [string]$BackupDir = ".\backups"
)

$ErrorActionPreference = "Stop"

function Require-File([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "$Label not found: $Path"
    }
}

function Get-EnvValue([string]$Path, [string]$Name) {
    $line = Get-Content -LiteralPath $Path |
        Where-Object { $_ -match "^\s*$Name\s*=" } |
        Select-Object -First 1
    if (-not $line) {
        throw "$Name was not found in $Path"
    }
    return (($line -split "=", 2)[1]).Trim().Trim('"').Trim("'")
}

function Invoke-Pg([string]$Exe, [string[]]$ArgsList) {
    $exePath = Join-Path $PgBin $Exe
    Require-File $exePath $Exe
    & $exePath @ArgsList
    if ($LASTEXITCODE -ne 0) {
        throw "$Exe failed with exit code $LASTEXITCODE"
    }
}

Require-File $EnvPath ".env file"
if (-not $env:LOCAL_PGPASSWORD -and -not $env:PGPASSWORD) {
    throw "Set LOCAL_PGPASSWORD or PGPASSWORD before running this script so local PostgreSQL can authenticate."
}

$pgPasswordBefore = $env:PGPASSWORD
if ($env:LOCAL_PGPASSWORD) {
    $env:PGPASSWORD = $env:LOCAL_PGPASSWORD
}

try {
    $sourceUrl = if ($env:NEON_DUMP_DSN) { $env:NEON_DUMP_DSN } else { Get-EnvValue $EnvPath "PG_DSN" }
    $directSourceUrl = $sourceUrl -replace "-pooler(\.)", '$1'
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $resolvedBackupDir = (New-Item -ItemType Directory -Force -Path $BackupDir).FullName
    $dumpPath = Join-Path $resolvedBackupDir "neon_$timestamp.dump"
    $tocPath = Join-Path $resolvedBackupDir "neon_$timestamp.toc"
    $filteredTocPath = Join-Path $resolvedBackupDir "neon_$timestamp.filtered.toc"

    $vectorControl = Join-Path (Split-Path $PgBin -Parent) "share\extension\vector.control"
    Require-File $vectorControl "pgvector extension control file"

    Write-Host "Checking Neon dump role can bypass source RLS..."
    $sourceRoleCheckSql = @"
SELECT CASE
    WHEN r.rolsuper OR r.rolbypassrls OR NOT EXISTS (
        SELECT 1
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind = 'r'
          AND c.relrowsecurity
          AND n.nspname NOT IN ('pg_catalog', 'information_schema')
          AND pg_get_userbyid(c.relowner) <> current_user
    )
    THEN 'ok'
    ELSE 'blocked'
END AS rls_dump_access
FROM pg_roles r
WHERE r.rolname = current_user;
"@
    $sourceRoleCheck = & (Join-Path $PgBin "psql.exe") -d $directSourceUrl -X -v ON_ERROR_STOP=1 -t -A -c $sourceRoleCheckSql
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to verify Neon dump role."
    }
    if (($sourceRoleCheck | Select-Object -Last 1).Trim() -ne "ok") {
        throw "The Neon source role cannot dump all RLS-protected rows. Set NEON_DUMP_DSN to a Neon owner/admin connection string, for example the neondb_owner direct connection URL."
    }

    Write-Host "Creating dump from Neon direct host..."
    Invoke-Pg "pg_dump.exe" @("-Fc", "-v", "--no-owner", "--no-acl", "-d", $directSourceUrl, "-f", $dumpPath)

    Write-Host "Creating filtered restore list without pg_search and BM25 index..."
    & (Join-Path $PgBin "pg_restore.exe") -l $dumpPath | Set-Content -LiteralPath $tocPath
    if ($LASTEXITCODE -ne 0) {
        throw "pg_restore.exe failed to list dump contents with exit code $LASTEXITCODE"
    }
    Get-Content -LiteralPath $tocPath |
        Where-Object {
            $_ -notmatch "EXTENSION.*pg_search" -and
            $_ -notmatch "COMMENT.*EXTENSION.*pg_search" -and
            $_ -notmatch "INDEX.*idx_chunks_bm25"
        } |
        Set-Content -LiteralPath $filteredTocPath

    $adminArgs = @("-X", "-h", $LocalHostName, "-p", "$LocalPort", "-U", $LocalUser, "-d", "postgres", "-v", "ON_ERROR_STOP=1")
    Write-Host "Dropping and recreating local database $LocalDbName..."
    Invoke-Pg "psql.exe" ($adminArgs + @("-c", "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$LocalDbName' AND pid <> pg_backend_pid();"))
    Invoke-Pg "psql.exe" ($adminArgs + @("-c", "DROP DATABASE IF EXISTS $LocalDbName;"))
    Invoke-Pg "psql.exe" ($adminArgs + @("-c", "CREATE DATABASE $LocalDbName WITH TEMPLATE template0;"))

    $localDbArgs = @("-X", "-h", $LocalHostName, "-p", "$LocalPort", "-U", $LocalUser, "-d", $LocalDbName, "-v", "ON_ERROR_STOP=1")
    Write-Host "Enabling local extensions..."
    Invoke-Pg "psql.exe" ($localDbArgs + @("-c", "CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm; CREATE EXTENSION IF NOT EXISTS pgcrypto;"))

    Write-Host "Restoring Neon dump into local database..."
    Invoke-Pg "pg_restore.exe" @(
        "-v",
        "--no-owner",
        "--no-acl",
        "-L",
        $filteredTocPath,
        "-h",
        $LocalHostName,
        "-p",
        "$LocalPort",
        "-U",
        $LocalUser,
        "-d",
        $LocalDbName,
        $dumpPath
    )

    Write-Host "Running migration smoke checks..."
    Invoke-Pg "psql.exe" ($localDbArgs + @("-c", "SELECT extname, extversion FROM pg_extension WHERE extname IN ('vector','pg_trgm','pgcrypto','plpgsql') ORDER BY extname;"))
    Invoke-Pg "psql.exe" ($localDbArgs + @("-c", "SELECT count(*) AS user_tables FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog','information_schema') AND table_type='BASE TABLE';"))
    Invoke-Pg "psql.exe" ($localDbArgs + @("-c", "SELECT count(*) AS rls_enabled_tables FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind='r' AND c.relrowsecurity AND n.nspname NOT IN ('pg_catalog','information_schema');"))
    Invoke-Pg "psql.exe" ($localDbArgs + @("-c", "SELECT count(*) AS policies FROM pg_policies WHERE schemaname NOT IN ('pg_catalog','information_schema');"))
    Invoke-Pg "psql.exe" ($localDbArgs + @("-c", "SELECT id FROM public.chunks WHERE embedding IS NOT NULL OR embedding_v2 IS NOT NULL LIMIT 1;"))
    Invoke-Pg "psql.exe" ($localDbArgs + @("-c", "SELECT c.id, ts_rank_cd(c.tsv, q.query) + similarity(COALESCE(c.text, ''), 'sql') AS score FROM public.chunks c CROSS JOIN websearch_to_tsquery('simple', 'sql') q(query) WHERE c.tsv @@ q.query OR similarity(COALESCE(c.text, ''), 'sql') > 0 ORDER BY score DESC LIMIT 1;"))

    Write-Host "Done. Set FULLTEXT_SEARCH_BACKEND=postgres and PG_DSN=postgresql://${LocalUser}:***@${LocalHostName}:$LocalPort/$LocalDbName for local app runs."
}
finally {
    $env:PGPASSWORD = $pgPasswordBefore
}
