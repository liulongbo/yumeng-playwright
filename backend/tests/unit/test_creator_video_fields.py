"""DATA-02 extraction rules for the seven content metrics and the eleven work fields.

The rules are asserted directly on the pure helpers so a regression in the *mapping* fails without a
database, and the integration test only has to prove the rows actually land.
"""

from datetime import UTC, datetime
from decimal import Decimal

from xingtu.creator_library import (
    _structured_member,
    _structured_scalar,
    _work_field_statuses,
    _work_number,
    _work_published,
    _work_text,
)


def _structured(data: object) -> dict[str, object]:
    return {"status": "COLLECTED", "value": {"kind": "structured", "data": data}}


def test_play_median_reads_the_nested_item_rate_leaf_not_the_top_level_decoy():
    """CD-08: the platform card 「播放量中位数」 is the nested `item_rate.play_mid`.

    Live-verified on 2026-10-16 for creator 6639192346380468227: the page shows 76.6w, which is the
    nested 766187; the top-level leaf holds 1399516 and is rendered nowhere.  Reading the decoy here
    is exactly the defect this round fixes, so both leaves are present in the fixture.
    """
    projection = {
        "spread.item_rate_metrics": _structured(
            {
                "item_num": {"value": 5, "overtake": 1},
                "play_mid": {"value": 766187, "overtake": 9923},
            }
        ),
        "spread.play_median": _structured("1399516"),
    }
    assert _structured_member(projection, "spread.item_rate_metrics", "play_mid", "value") == 766187
    assert _structured_scalar(projection, "spread.play_median") == Decimal("1399516")


def test_label_only_play_mid_stays_null_instead_of_becoming_zero():
    """A `play_mid` envelope with only {"label": ""} is absence, never 0."""
    projection = {"spread.item_rate_metrics": _structured({"play_mid": {"label": ""}})}
    assert _structured_member(projection, "spread.item_rate_metrics", "play_mid", "value") is None


def test_metric_helpers_ignore_uncollected_and_wrong_shapes():
    failed = {"status": "FAILED", "value": None}
    assert _structured_scalar({"spread.average_likes": failed}, "spread.average_likes") is None
    # A member object is not a scalar leaf, and a missing key is not a value.
    assert (
        _structured_scalar(
            {"spread.average_likes": _structured({"value": 1})}, "spread.average_likes"
        )
        is None
    )
    assert _structured_scalar({}, "spread.average_likes") is None
    assert (
        _structured_member(
            {"spread.item_rate_metrics": _structured({"play_mid": "766187"})},
            "spread.item_rate_metrics",
            "play_mid",
            "value",
        )
        is None
    )


def test_work_field_text_and_number_keep_real_zero_and_reject_blanks():
    item = {"title": "  ", "item_title": "真实标题", "item_cover": "", "play": 0, "like": "12345"}
    assert _work_text(item, "title", "item_title") == "真实标题"
    assert _work_text(item, "item_cover") is None
    assert _work_number(item, "play") == 0
    assert _work_number(item, "like") == Decimal("12345")
    assert _work_number(item, "share") is None
    # Every collected work record carries these keys as real JSON numbers (3064/3064, audited
    # 2026-10-16). A grouped string is therefore a schema change, not a value to re-interpret
    # silently: it stays NULL instead of being parsed into a number we cannot vouch for.
    assert _work_number({"like": "12,345"}, "like") is None


def test_work_published_prefers_the_exact_unix_second_and_falls_back_to_item_date():
    assert _work_published({"create_time": 1790940267, "item_date": "1999-01-01"}) == datetime(
        2026, 10, 2, 11, 24, 27, tzinfo=UTC
    )
    assert _work_published({"item_date": "2026-10-02"}) == datetime(2026, 10, 2, tzinfo=UTC)
    assert _work_published({"item_date": "not a date"}) is None
    assert _work_published({}) is None


def test_work_field_statuses_name_the_two_fields_the_platform_never_returns():
    """`subtitle` and `favorite_count` appeared in 0 of 3064 collected work records (2026-10-16).

    They must read as an explicit platform absence; a bare NULL could not be told apart from a
    failed read, and a 0 filler would be a fabricated value.
    """
    statuses = _work_field_statuses(
        {
            "item_id": "7692029874500553679",
            "core_user_id": "103411567572",
            "title": "作品",
            "item_cover": "tos-cn-i-0813c001/abc",
            "play": 0,
            "like": 0,
            "comment": 0,
            "share": 0,
            "item_date": "2026-10-02",
        }
    )
    assert statuses["subtitle"] == "NOT_PROVIDED"
    assert statuses["favorite_count"] == "NOT_PROVIDED"
    assert statuses["cover"] == "COLLECTED"
    assert statuses["published_at"] == "COLLECTED"
    assert statuses["play_count"] == "COLLECTED"


def test_work_field_statuses_mark_an_empty_cover_as_not_provided():
    statuses = _work_field_statuses({"item_id": "1", "title": "t", "item_cover": ""})
    assert statuses["cover"] == "NOT_PROVIDED"
    assert statuses["favorite_count"] == "NOT_PROVIDED"
