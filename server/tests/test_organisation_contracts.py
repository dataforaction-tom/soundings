"""Round-trip tests for OrganisationRef + GrantRef (Phase 4 design §4.6)."""

from datetime import UTC, datetime

from soundings.contracts.organisation import GrantRef, OrganisationRef
from soundings.contracts.source_ref import SourceRef


def _src(source_id: str = "charity_commission") -> SourceRef:
    return SourceRef(
        source_id=source_id,
        source_label=source_id,
        publisher="test",
        retrieved_at=datetime.now(tz=UTC),
        cache_status="cached",
        licence="CC0",
    )


def test_grant_ref_round_trips() -> None:
    grant = GrantRef(
        funder="Test Foundation",
        amount=12_500.00,
        currency="GBP",
        date="2024-08-12",
        purpose="Community youth work",
        source=_src("threesixtygiving"),
    )
    restored = GrantRef.model_validate(grant.model_dump(mode="json"))
    assert restored == grant


def test_organisation_ref_round_trips_with_empty_grants() -> None:
    org = OrganisationRef(
        id="charity_commission:1234567",
        name="Test Charity",
        classification=["youth", "community"],
        registered_address_place_id="ltla24:E06000004",
        operates_in_place_ids=["ltla24:E06000004"],
        recent_grants=[],
        source=_src(),
    )
    restored = OrganisationRef.model_validate(org.model_dump(mode="json"))
    assert restored == org
    assert restored.recent_grants == []


def test_organisation_ref_carries_recent_grants() -> None:
    grants = [
        GrantRef(
            funder="Funder A",
            amount=5_000.0,
            currency="GBP",
            date="2024-06-01",
            purpose="purpose A",
            source=_src("threesixtygiving"),
        ),
        GrantRef(
            funder="Funder B",
            amount=8_000.0,
            currency="GBP",
            date="2024-09-15",
            purpose="purpose B",
            source=_src("threesixtygiving"),
        ),
    ]
    org = OrganisationRef(
        id="charity_commission:7654321",
        name="Another Charity",
        classification=[],
        registered_address_place_id="ltla24:E06000004",
        operates_in_place_ids=["ltla24:E06000004"],
        recent_grants=grants,
        source=_src(),
    )
    restored = OrganisationRef.model_validate(org.model_dump(mode="json"))
    assert len(restored.recent_grants) == 2
    assert restored.recent_grants[0].funder == "Funder A"


def test_organisation_ref_optional_address_place() -> None:
    """Some charities have non-UK postcodes that don't resolve to a place;
    `registered_address_place_id` must be None-able, not required."""
    org = OrganisationRef(
        id="charity_commission:9999999",
        name="Overseas Charity",
        classification=[],
        registered_address_place_id=None,
        operates_in_place_ids=[],
        recent_grants=[],
        source=_src(),
    )
    restored = OrganisationRef.model_validate(org.model_dump(mode="json"))
    assert restored.registered_address_place_id is None
