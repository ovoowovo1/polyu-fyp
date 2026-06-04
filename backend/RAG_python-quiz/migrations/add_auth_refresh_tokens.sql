-- Add revocable refresh token storage for access token renewal.

CREATE TABLE IF NOT EXISTS public.auth_refresh_tokens (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    token_hash text NOT NULL UNIQUE,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    replaced_by_token_id uuid REFERENCES public.auth_refresh_tokens(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    last_used_at timestamptz
);

CREATE INDEX IF NOT EXISTS idx_auth_refresh_tokens_user_id
    ON public.auth_refresh_tokens(user_id);

CREATE INDEX IF NOT EXISTS idx_auth_refresh_tokens_active_lookup
    ON public.auth_refresh_tokens(token_hash)
    WHERE revoked_at IS NULL;

ALTER TABLE public.auth_refresh_tokens ENABLE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION app_security.auth_store_refresh_token(
    target_user_id uuid,
    new_token_hash text,
    new_expires_at timestamptz
)
RETURNS uuid
LANGUAGE sql
SECURITY DEFINER
SET search_path = public, app_security
AS $$
    INSERT INTO public.auth_refresh_tokens (user_id, token_hash, expires_at)
    VALUES (target_user_id, new_token_hash, new_expires_at)
    RETURNING id
$$;

CREATE OR REPLACE FUNCTION app_security.auth_rotate_refresh_token(
    current_token_hash text,
    next_token_hash text,
    next_expires_at timestamptz
)
RETURNS TABLE (
    id uuid,
    email text,
    full_name text,
    role text
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, app_security
AS $$
DECLARE
    current_token public.auth_refresh_tokens%ROWTYPE;
    next_token_id uuid;
BEGIN
    SELECT *
    INTO current_token
    FROM public.auth_refresh_tokens
    WHERE token_hash = current_token_hash
    FOR UPDATE;

    IF current_token.id IS NULL
       OR current_token.revoked_at IS NOT NULL
       OR current_token.expires_at <= now() THEN
        RETURN;
    END IF;

    INSERT INTO public.auth_refresh_tokens (user_id, token_hash, expires_at)
    VALUES (current_token.user_id, next_token_hash, next_expires_at)
    RETURNING auth_refresh_tokens.id INTO next_token_id;

    UPDATE public.auth_refresh_tokens
    SET revoked_at = now(),
        replaced_by_token_id = next_token_id,
        last_used_at = now()
    WHERE auth_refresh_tokens.id = current_token.id;

    RETURN QUERY
    SELECT u.id, u.email, u.full_name, u.role
    FROM public.users u
    WHERE u.id = current_token.user_id;
END;
$$;

CREATE OR REPLACE FUNCTION app_security.auth_revoke_refresh_token(
    current_token_hash text
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, app_security
AS $$
BEGIN
    UPDATE public.auth_refresh_tokens
    SET revoked_at = now(),
        last_used_at = now()
    WHERE token_hash = current_token_hash
      AND revoked_at IS NULL
      AND expires_at > now();

    RETURN FOUND;
END;
$$;
