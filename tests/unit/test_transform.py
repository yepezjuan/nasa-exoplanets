import pytest

from exoplanet_archive.ingest.transform import check_snapshot, content_hash, transform


def test_fixture_rows_all_validate(raw_rows):
    result = transform(raw_rows)
    assert result.rejected == []
    assert len(result.rows) == len(raw_rows)


def test_maps_archive_columns_to_our_names(raw_rows):
    raw = raw_rows[0]
    row = transform([raw]).rows[0]
    assert row["pl_name"] == raw["pl_name"]
    assert row["discovery_method"] == raw["discoverymethod"]
    assert row["orbital_period_days"] == raw["pl_orbper"]
    assert row["ra_deg"] == raw["ra"]
    assert row["dec_deg"] == raw["dec"]


def test_null_measurements_are_kept(raw_rows):
    raw = {**raw_rows[0], "pl_eqt": None, "pl_rade": None}
    result = transform([raw])
    assert result.rejected == []
    assert result.rows[0]["eq_temp_k"] is None
    assert result.rows[0]["radius_earth"] is None


@pytest.mark.parametrize(
    "change",
    [
        {"pl_name": None},
        {"pl_name": "   "},
        {"ra": None},
        {"ra": 360.5},
        {"dec": -91},
        {"disc_year": "not a year"},
        {"pl_rade": "large"},
    ],
)
def test_malformed_rows_are_rejected_without_stopping(raw_rows, change):
    bad = {**raw_rows[0], **change}
    result = transform([bad, raw_rows[1]])
    assert [row["pl_name"] for row in result.rows] == [raw_rows[1]["pl_name"]]
    assert len(result.rejected) == 1
    assert result.fetched == 2


def test_duplicate_names_are_rejected(raw_rows):
    result = transform([raw_rows[0], raw_rows[0]])
    assert len(result.rows) == 1
    assert result.rejected[0]["errors"] == ["duplicate pl_name"]


def test_content_hash_ignores_key_order_and_detects_changes():
    assert content_hash({"a": 1, "b": 2}) == content_hash({"b": 2, "a": 1})
    assert content_hash({"a": 1}) != content_hash({"a": 2})


@pytest.mark.parametrize(
    ("valid", "rejected", "current", "expected_fragment"),
    [
        (1000, 0, 1000, None),
        (1000, 0, 0, None),  # The first ingest has nothing to compare against.
        (900, 0, 1000, None),  # Exactly at the row limit.
        (990, 10, 0, None),  # Exactly at the reject limit.
        (899, 0, 1000, "under 90%"),
        (989, 11, 0, "over the 1.0% limit"),
        (0, 0, 0, "no valid rows"),
        (0, 5, 1000, "no valid rows"),
    ],
)
def test_check_snapshot(valid, rejected, current, expected_fragment):
    reason = check_snapshot(
        valid=valid,
        rejected=rejected,
        current_count=current,
        min_row_ratio=0.9,
        max_reject_ratio=0.01,
    )
    if expected_fragment is None:
        assert reason is None
    else:
        assert expected_fragment in reason
