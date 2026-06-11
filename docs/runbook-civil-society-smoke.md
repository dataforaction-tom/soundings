# Runbook — civil society panel smoke

After any change to `data.organisation`, the CC loader, the
`get_civil_society_profile` orchestrator method, or the
`<CivilSocietyPanel>` component:

1. Ensure `make up` and the CC loader has been re-run since the change.
2. Visit `/place/ltla24:E06000047` (County Durham) — expect ~1,000
   charities, populated income chart and registration trend.
3. Visit `/place/ltla24:W06000023` (Powys) — expect non-zero totals.
4. Visit `/place/ltla24:S12000033` (Aberdeen) — expect the panel to be
   suppressed; rest of the page should still render.

If the panel renders but `median_income` is `null` or all bucket
counts are 0, re-run the CC loader: the `raw` JSONB on
`data.organisation` is probably missing the income/date fields the
panel depends on.
