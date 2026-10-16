from xingtu.contracts import AttributeFilterEntry, AttributeFilterMatchSpec
from xingtu.observer import attribute_filters_match


def test_null_attribute_filter_is_empty_multiset_for_keyword_only_plan():
    spec = AttributeFilterMatchSpec(path="attribute_filter")

    assert attribute_filters_match({"attribute_filter": None}, spec, [])
    assert not attribute_filters_match(
        {"attribute_filter": None},
        spec,
        [AttributeFilterEntry(field_name="gender", field_value="2")],
    )


def test_unspecified_rel_id_matches_but_explicit_rel_id_is_enforced():
    payload = {
        "attribute_filter": [
            {
                "field": {"field_name": "price_by_video_type__ge", "rel_id": "2"},
                "field_value": "0",
            },
            {
                "field": {"field_name": "gender", "rel_id": "7"},
                "field_value": "2",
            },
        ]
    }
    optional_rel = AttributeFilterMatchSpec(
        path="attribute_filter",
        allowed_static=[
            AttributeFilterEntry(field_name="price_by_video_type__ge", field_value="0")
        ],
    )
    assert attribute_filters_match(
        payload,
        optional_rel,
        [AttributeFilterEntry(field_name="gender", field_value="2")],
    )
    assert not attribute_filters_match(
        payload,
        optional_rel,
        [AttributeFilterEntry(field_name="gender", rel_id="8", field_value="2")],
    )


def test_allowed_static_is_optional_but_duplicates_and_residue_are_rejected():
    spec = AttributeFilterMatchSpec(
        path="attribute_filter",
        allowed_static=[AttributeFilterEntry(field_name="price", field_value="0")],
    )
    assert attribute_filters_match({"attribute_filter": []}, spec, [])
    assert not attribute_filters_match(
        {
            "attribute_filter": [
                {"field": {"field_name": "price"}, "field_value": "0"},
                {"field": {"field_name": "price"}, "field_value": "0"},
            ]
        },
        spec,
        [],
    )
