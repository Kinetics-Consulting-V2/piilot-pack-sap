"""Tests for ``piilot_pack_sap.odata_validator`` — whitelist v1 grammar."""

from __future__ import annotations

import pytest

from piilot_pack_sap.odata_validator import (
    DEFAULT_MAX_TOP,
    ValidationError,
    validate_request,
)


# ---------- HTTP method ------------------------------------------------------


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
def test_only_get_allowed(method: str) -> None:
    with pytest.raises(ValidationError) as exc:
        validate_request(method, {})
    assert exc.value.code == "method_not_allowed"


def test_get_with_no_params_is_valid() -> None:
    validate_request("GET", {})  # must not raise


def test_get_lowercase_is_accepted() -> None:
    validate_request("get", {})


# ---------- Query options whitelist -----------------------------------------


@pytest.mark.parametrize(
    "option",
    ["$expand", "$batch", "$inlinecount", "$links", "$value", "$ref", "$search"],
)
def test_explicitly_forbidden_options_rejected(option: str) -> None:
    with pytest.raises(ValidationError) as exc:
        validate_request("GET", {option: "x"})
    assert exc.value.code == "forbidden_query_option"


def test_unknown_dollar_option_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        validate_request("GET", {"$foobar": "x"})
    assert exc.value.code == "unknown_query_option"


def test_non_dollar_param_is_ignored() -> None:
    # SAP gateway often takes language hints like sap-language=fr — anything
    # that does not start with $ is out of the OData spec scope and is left
    # to the upstream gateway.
    validate_request("GET", {"sap-language": "fr"})


# ---------- $top / $skip / $format ------------------------------------------


@pytest.mark.parametrize("raw", ["1", "10", "1000"])
def test_top_valid(raw: str) -> None:
    validate_request("GET", {"$top": raw})


@pytest.mark.parametrize(
    "raw,expected_code",
    [
        ("abc", "invalid_top"),
        ("", "invalid_top"),
        ("-1", "invalid_top"),
        ("1.5", "invalid_top"),
        ("0", "invalid_top"),
        ("10001", "top_exceeds_max"),
    ],
)
def test_top_invalid(raw: str, expected_code: str) -> None:
    with pytest.raises(ValidationError) as exc:
        validate_request("GET", {"$top": raw}, max_top=DEFAULT_MAX_TOP)
    assert exc.value.code == expected_code


def test_top_respects_custom_max() -> None:
    validate_request("GET", {"$top": "50"}, max_top=50)
    with pytest.raises(ValidationError, match="exceeds the configured max"):
        validate_request("GET", {"$top": "51"}, max_top=50)


@pytest.mark.parametrize("raw", ["0", "10", "999999"])
def test_skip_valid(raw: str) -> None:
    validate_request("GET", {"$skip": raw})


@pytest.mark.parametrize("raw", ["-1", "abc", "1.5", ""])
def test_skip_invalid(raw: str) -> None:
    with pytest.raises(ValidationError) as exc:
        validate_request("GET", {"$skip": raw})
    assert exc.value.code == "invalid_skip"


def test_format_json_only() -> None:
    validate_request("GET", {"$format": "json"})
    validate_request("GET", {"$format": "JSON"})  # case-insensitive


@pytest.mark.parametrize("raw", ["xml", "atom", "csv", ""])
def test_format_rejected(raw: str) -> None:
    with pytest.raises(ValidationError) as exc:
        validate_request("GET", {"$format": raw})
    assert exc.value.code == "invalid_format"


# ---------- $count -----------------------------------------------------------


def test_count_v2_inline_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        validate_request("GET", {"$count": "true"}, version="v2")
    assert exc.value.code == "count_inline_v2_unsupported"


@pytest.mark.parametrize("raw", ["true", "false", "TRUE"])
def test_count_v4_valid(raw: str) -> None:
    validate_request("GET", {"$count": raw}, version="v4")


@pytest.mark.parametrize("raw", ["yes", "1", "0", "maybe"])
def test_count_v4_invalid(raw: str) -> None:
    with pytest.raises(ValidationError) as exc:
        validate_request("GET", {"$count": raw}, version="v4")
    assert exc.value.code == "invalid_count"


# ---------- $select ----------------------------------------------------------


def test_select_single_prop() -> None:
    validate_request("GET", {"$select": "BusinessPartner"})


def test_select_multiple_props() -> None:
    validate_request("GET", {"$select": "BusinessPartner, FirstName ,LastName"})


def test_select_empty_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        validate_request("GET", {"$select": "  "})
    assert exc.value.code == "empty_select"


@pytest.mark.parametrize(
    "value",
    [
        "to_Customer/Name",  # navigation path
        "BP.Name",  # dotted path
        "First Name",  # space
        "FirstName;DROP",  # SQL-style injection
    ],
)
def test_select_rejects_complex_paths(value: str) -> None:
    with pytest.raises(ValidationError) as exc:
        validate_request("GET", {"$select": value})
    assert exc.value.code == "invalid_identifier"


def test_select_unknown_property_when_allowed_set_given() -> None:
    with pytest.raises(ValidationError) as exc:
        validate_request(
            "GET",
            {"$select": "FirstName, Unknown"},
            allowed_properties={"FirstName", "LastName"},
        )
    assert exc.value.code == "unknown_property"


# ---------- $orderby ---------------------------------------------------------


def test_orderby_default_asc() -> None:
    validate_request("GET", {"$orderby": "FirstName"})


def test_orderby_explicit_directions() -> None:
    validate_request("GET", {"$orderby": "FirstName asc, LastName desc"})


def test_orderby_unknown_direction_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        validate_request("GET", {"$orderby": "FirstName ascending"})
    assert exc.value.code == "invalid_orderby_direction"


def test_orderby_too_many_tokens_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        validate_request("GET", {"$orderby": "FirstName asc desc"})
    assert exc.value.code == "invalid_orderby"


def test_orderby_navigation_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        validate_request("GET", {"$orderby": "to_Customer/Name asc"})
    assert exc.value.code == "invalid_identifier"


# ---------- $apply (aggregate) -----------------------------------------------


def test_apply_aggregate_sum() -> None:
    validate_request("GET", {"$apply": "aggregate(Amount with sum as Total)"})


def test_apply_aggregate_multiple() -> None:
    validate_request(
        "GET",
        {
            "$apply": (
                "aggregate(Amount with sum as Total, Amount with avg as Mean,"
                " Id with countdistinct as Distinct)"
            )
        },
    )


def test_apply_aggregate_count_without_prop_ok() -> None:
    validate_request("GET", {"$apply": "aggregate(with count as N)"})


def test_apply_aggregate_invalid_op_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        validate_request("GET", {"$apply": "aggregate(Amount with median as M)"})
    assert exc.value.code == "invalid_aggregate_op"


def test_apply_non_aggregate_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        validate_request("GET", {"$apply": "filter(Status eq 'X')"})
    assert exc.value.code == "invalid_apply"


def test_apply_aggregate_groupby_rejected() -> None:
    # groupby is OData spec but explicitly out of v1 whitelist.
    with pytest.raises(ValidationError) as exc:
        validate_request(
            "GET", {"$apply": "groupby((Cat), aggregate(Amount with sum as T))"}
        )
    assert exc.value.code == "invalid_apply"


def test_apply_aggregate_unknown_property() -> None:
    with pytest.raises(ValidationError) as exc:
        validate_request(
            "GET",
            {"$apply": "aggregate(Amount with sum as Total)"},
            allowed_properties={"FirstName"},
        )
    assert exc.value.code == "unknown_property"


# ---------- $filter — basic shapes -------------------------------------------


@pytest.mark.parametrize(
    "expr",
    [
        "FirstName eq 'John'",
        "Age gt 18",
        "Price ge 100 and Price le 500",
        "Status ne 'X' or Status ne 'Y'",
        "not (IsArchived eq true)",
        "((A eq 1) or (B eq 2)) and C eq 3",
        "IsActive eq true",
        "Score eq null",
        "Discount eq 0.15",
        "Discount eq -0.5",
    ],
)
def test_filter_valid(expr: str) -> None:
    validate_request("GET", {"$filter": expr})


def test_filter_v2_datetime_literal_valid() -> None:
    validate_request(
        "GET",
        {"$filter": "CreatedAt ge datetime'2026-01-01T00:00:00'"},
        version="v2",
    )


def test_filter_v2_datetimeoffset_literal_valid() -> None:
    validate_request(
        "GET",
        {
            "$filter": (
                "CreatedAt ge datetimeoffset'2026-01-01T00:00:00Z'"
            )
        },
        version="v2",
    )


def test_filter_v2_datetime_literal_rejected_in_v4() -> None:
    with pytest.raises(ValidationError) as exc:
        validate_request(
            "GET",
            {"$filter": "CreatedAt ge datetime'2026-01-01T00:00:00'"},
            version="v4",
        )
    assert exc.value.code == "v2_datetime_literal_in_v4"


def test_filter_empty_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        validate_request("GET", {"$filter": "   "})
    assert exc.value.code == "empty_filter"


# ---------- $filter — forbidden shapes (the security-critical bit) ----------


@pytest.mark.parametrize(
    "expr,reason",
    [
        # Forbidden lambda operators — '/' is rejected at tokenizer level (more
        # defensive than parser-level: any path-like syntax in $filter dies
        # before grammar can interpret it).
        ("Items/any(i: i/Price gt 10)", "invalid_filter_char"),
        ("Items/all(i: i/Price gt 10)", "invalid_filter_char"),
        # Function calls in $filter — these tokenize cleanly (no '/' or '.'),
        # so the parser reaches the IDENT-then-LPAREN rule and rejects.
        ("contains(Name, 'foo')", "function_call_forbidden"),
        ("startswith(Name, 'A')", "function_call_forbidden"),
        ("endswith(Name, 'Z')", "function_call_forbidden"),
        ("substring(Name, 0, 3) eq 'abc'", "function_call_forbidden"),
        ("length(Name) gt 5", "function_call_forbidden"),
        ("tolower(Name) eq 'foo'", "function_call_forbidden"),
        ("year(CreatedAt) eq 2026", "function_call_forbidden"),
        # OData cast / isof — qualified type names like 'Edm.String' carry a
        # '.' which fails the tokenizer first.
        ("cast(Id, Edm.String) eq '1'", "invalid_filter_char"),
        ("isof(Id, Edm.Int32)", "invalid_filter_char"),
        # Navigation in property reference — '/' rejected at tokenizer level.
        ("to_Customer/Name eq 'John'", "invalid_filter_char"),
        # Unclosed parens
        ("(Name eq 'X'", "unclosed_paren"),
        # Trailing garbage
        ("Name eq 'X' garbage", "trailing_filter_tokens"),
        # Misplaced operators
        ("eq Name 'X'", "misplaced_comparison"),
        ("and Name eq 'X'", "misplaced_operator"),
        # SQL-style injection attempt
        ("Name eq 'X' ; DROP TABLE", "invalid_filter_char"),
        # Operator typo (= is not an OData operator and is rejected at tokenizer)
        ("Name = 'X'", "invalid_filter_char"),
    ],
)
def test_filter_forbidden(expr: str, reason: str) -> None:
    with pytest.raises(ValidationError) as exc:
        validate_request("GET", {"$filter": expr})
    assert exc.value.code == reason, (
        f"expected code {reason!r} for {expr!r}, got {exc.value.code!r} "
        f"({exc.value.message})"
    )


def test_filter_unknown_property_rejected_with_allowed_set() -> None:
    with pytest.raises(ValidationError) as exc:
        validate_request(
            "GET",
            {"$filter": "Phantom eq 'X'"},
            allowed_properties={"FirstName"},
        )
    assert exc.value.code == "unknown_property"


def test_filter_known_property_accepted_with_allowed_set() -> None:
    validate_request(
        "GET",
        {"$filter": "FirstName eq 'John'"},
        allowed_properties={"FirstName"},
    )


# ---------- $filter — string literal edge cases -----------------------------


def test_filter_string_with_escaped_quote() -> None:
    # OData escapes single quotes by doubling them.
    validate_request("GET", {"$filter": "Name eq 'O''Brien'"})


def test_filter_unicode_in_string_literal() -> None:
    # Strings may contain arbitrary characters between quotes.
    validate_request("GET", {"$filter": "Name eq 'François'"})


def test_filter_invalid_non_ascii_outside_strings_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        validate_request("GET", {"$filter": "Naïve eq 'X'"})
    assert exc.value.code == "invalid_filter_char"


# ---------- Fuzzing pass: a battery of suspicious inputs ---------------------


_FUZZ_PAYLOADS: list[str] = [
    "Name eq 'X' or 1 eq 1",  # tautology — should still parse but ok logic
    "Name eq 'X'; SELECT * FROM users",  # SQL injection style
    "$filter=true",  # leftover URL form
    "Name eq 'X'/**/and/**/Age gt 0",  # comment injection
    "Name eq 'X' UNION SELECT 1",
    "Name eq 'X' AND 'x'='x'",
    "Name eq cast(null, Edm.String)",
    "exec('rm -rf /')",
    "Name eq @inject",  # parameter alias style
    "Name eq 'X' && Age gt 0",  # JS operator typo
    "Name eq 'X' || Age gt 0",
    "Name eq 'X'%00",  # null byte
    "Name eq 'X'%20OR%20'1'%3D'1'",  # url-encoded mix
    "Name eq 'X' ' ' eq 'Y'",  # double-string trick
]


@pytest.mark.parametrize("payload", _FUZZ_PAYLOADS)
def test_filter_fuzz_payloads_dont_crash_and_either_pass_or_raise_validation(
    payload: str,
) -> None:
    """Every fuzz payload must either pass cleanly or raise ValidationError.

    Anything else (TypeError, AttributeError, IndexError, etc.) is a bug —
    the validator must always terminate with a controlled outcome.
    """
    try:
        validate_request("GET", {"$filter": payload})
    except ValidationError:
        pass


def test_fuzz_payload_with_sql_semicolon_is_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_request(
            "GET", {"$filter": "Name eq 'X'; SELECT * FROM users"}
        )


def test_fuzz_payload_with_comment_is_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_request(
            "GET", {"$filter": "Name eq 'X'/**/and/**/Age gt 0"}
        )


def test_fuzz_payload_with_null_byte_is_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_request("GET", {"$filter": "Name eq 'X'\x00"})


# ---------- Combined realistic queries --------------------------------------


def test_realistic_business_partner_query() -> None:
    validate_request(
        "GET",
        {
            "$filter": (
                "BusinessPartnerCategory eq '2' and CreationDate ge "
                "datetime'2026-01-01T00:00:00'"
            ),
            "$select": "BusinessPartner,BusinessPartnerFullName,CreationDate",
            "$orderby": "CreationDate desc",
            "$top": "100",
            "$format": "json",
        },
        version="v2",
    )


def test_realistic_aggregation_query_v4() -> None:
    validate_request(
        "GET",
        {
            "$filter": "Year ge 2026",
            "$apply": "aggregate(Amount with sum as Total)",
            "$count": "true",
            "$format": "json",
        },
        version="v4",
    )
