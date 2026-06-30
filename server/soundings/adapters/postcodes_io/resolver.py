"""Postcode → LTLA resolution helper.

Shared by the bulk loaders (Charity Commission, Companies House) that
publish UK postcodes and need to attach each to a Soundings LTLA
`place_id`.

Cache strategy: `geography.postcode` is the durable lookup table for
postcode → place_id. The resolver checks there first for every incoming
postcode and only batches the unresolved ones to postcodes.io. Re-running
a monthly loader against a fully-seeded `geography.postcode` is a no-op
against the postcodes.io API — at hundreds of thousands of postcodes that
matters, as we'd otherwise hammer the upstream every load.
"""

from sqlalchemy import text

from soundings.adapters.postcodes_io.adapter import PostcodesIoAdapter, _normalise_postcode


async def resolve_postcodes_to_ltlas(
    postcodes_io: PostcodesIoAdapter,
    postcodes: list[str],
) -> dict[str, str | None]:
    """Return a dict keyed by the *original* postcode string,
    mapping to an `ltla24:E...` place_id or None if unresolved.

    Idempotent: postcodes already in `geography.postcode` short-circuit
    without hitting postcodes.io. The bulk endpoint is only called for
    postcodes not yet cached.
    """
    if not postcodes:
        return {}

    normalised_to_originals: dict[str, list[str]] = {}
    for original in postcodes:
        norm = _normalise_postcode(original)
        normalised_to_originals.setdefault(norm, []).append(original)

    cached_ltla_by_norm: dict[str, str | None] = {}
    norm_keys = list(normalised_to_originals.keys())
    async with postcodes_io._engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT postcode, ltla24 FROM geography.postcode WHERE postcode = ANY(:codes)"
                ),
                {"codes": norm_keys},
            )
        ).all()
    for row in rows:
        cached_ltla_by_norm[row.postcode] = row.ltla24

    missing = [norm for norm in normalised_to_originals if norm not in cached_ltla_by_norm]
    if missing:
        fetched = await postcodes_io.bulk_upsert(missing)
        for norm, lookup in fetched.items():
            cached_ltla_by_norm[norm] = lookup.ltla24 if lookup is not None else None
        for norm in missing:
            cached_ltla_by_norm.setdefault(norm, None)

    out: dict[str, str | None] = {}
    for norm, originals in normalised_to_originals.items():
        ltla = cached_ltla_by_norm.get(norm)
        for original in originals:
            out[original] = ltla
    return out
