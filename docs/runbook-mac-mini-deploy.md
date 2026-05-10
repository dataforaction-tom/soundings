# Runbook: Mac mini smoke deploy

> **Status:** Phase 0. The stack here is a "does it route" smoke test, not a
> production deploy. Real serving happens after Phase 1.

## Prerequisites on the Mac mini

- Docker Desktop or Colima.
- A working `cloudflared` installation with a tunnel already terminating
  on this machine. (Existing Good Ship infra.)
- A spare hostname on your domain (e.g. `soundings.<your-domain>`) that is
  not already routed by another tunnel rule.

## One-time setup

1. Clone the repo and `cd soundings`.
2. Generate `.env` with a strong `POSTGRES_PASSWORD`:
   ```bash
   cp .env.example .env
   # Edit POSTGRES_PASSWORD to something other than the default.
   ```
3. Bring up the stack:
   ```bash
   make up
   make migrate
   make seed-light    # ~5 min on first run
   ```
4. Verify locally:
   ```bash
   curl -fsS http://localhost:8088/healthz
   ```
   You should see `{"status":"ok","checks":{...}}`.

## Wire up Cloudflare Tunnel

Edit `~/.cloudflared/config.yml` and **add** an additive rule above the
catch-all:

```yaml
ingress:
  - hostname: soundings.<your-domain>
    service: http://localhost:8088
  # …existing rules below, unchanged…
```

Restart cloudflared (process manager command depends on how it's installed
on this Mac mini — `sudo launchctl kickstart -k system/com.cloudflare.cloudflared`
or equivalent).

Verify externally:

```bash
curl -fsS https://soundings.<your-domain>/healthz
```

## Rollback

`make down` stops the soundings stack but leaves cloudflared and the rest
of the existing infra untouched. To remove the public hostname, delete the
ingress rule from `~/.cloudflared/config.yml` and restart cloudflared.
