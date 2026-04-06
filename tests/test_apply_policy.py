"""Tests for the apply_policy module."""

from src.apply_policy import (
    DEFAULT_COMPANY_BLOCKLISTS,
    DEFAULT_TITLE_BLOCKLISTS,
    evaluate_company_quality,
    evaluate_title_quality,
    evaluate_job_policy,
    format_policy_reasons,
)


class TestEvaluateCompanyQuality:
    def test_allows_direct_employer(self):
        decision = evaluate_company_quality("Acme Bank")

        assert decision.allowed is True
        assert decision.reasons == ()

    def test_blocks_staffing_company(self):
        decision = evaluate_company_quality("North Star Staffing")

        assert decision.allowed is False
        assert len(decision.reasons) == 1
        assert decision.reasons[0].code == "company:recruiting_staffing"
        assert decision.reasons[0].matched_term == "staffing"

    def test_blocks_consulting_company(self):
        decision = evaluate_company_quality("Blue River Consulting")

        assert decision.allowed is False
        assert decision.reasons[0].code == "company:consulting"

    def test_supports_custom_blocklists(self):
        decision = evaluate_company_quality(
            "Acme Labs",
            blocklists={"custom": ("labs",)},
        )

        assert decision.allowed is False
        assert decision.reasons[0].code == "company:custom"
        assert decision.reasons[0].matched_term == "labs"

    def test_empty_blocklists_can_disable_defaults(self):
        decision = evaluate_company_quality(
            "North Star Staffing",
            blocklists={},
        )

        assert decision.allowed is True
        assert decision.reasons == ()


class TestEvaluateTitleQuality:
    def test_allows_standard_full_time_title(self):
        decision = evaluate_title_quality("Compliance Analyst")

        assert decision.allowed is True
        assert decision.reasons == ()

    def test_blocks_hourly_temp_signal(self):
        decision = evaluate_title_quality("Compliance Analyst - Contract-to-Hire")

        assert decision.allowed is False
        assert decision.reasons[0].code == "title:hourly_temp"
        assert decision.reasons[0].matched_term == "contract-to-hire"

    def test_blocks_recruiting_signal(self):
        decision = evaluate_title_quality("Senior Recruiter")

        assert decision.allowed is False
        assert decision.reasons[0].code == "title:recruiting_staffing"

    def test_blocks_consulting_signal(self):
        decision = evaluate_title_quality("Risk Consultant")

        assert decision.allowed is False
        assert decision.reasons[0].code == "title:consulting"


class TestEvaluateJobPolicy:
    def test_aggregates_company_and_title_reasons(self):
        decision = evaluate_job_policy(
            {
                "company": "Summit Staffing",
                "title": "Compliance Analyst - Temporary",
            }
        )

        assert decision.allowed is False
        assert [reason.code for reason in decision.reasons] == [
            "company:recruiting_staffing",
            "title:hourly_temp",
        ]

    def test_handles_missing_fields(self):
        decision = evaluate_job_policy({})

        assert decision.allowed is True
        assert decision.reasons == ()

    def test_format_policy_reasons_returns_stable_summary(self):
        decision = evaluate_job_policy(
            {
                "company": "Blue River Consulting",
                "title": "Risk Consultant",
            }
        )

        summary = format_policy_reasons(decision.reasons)

        assert "company policy 'consulting'" in summary
        assert "title policy 'consulting'" in summary


class TestDefaultBlocklists:
    def test_default_blocklists_cover_required_categories(self):
        assert "recruiting_staffing" in DEFAULT_COMPANY_BLOCKLISTS
        assert "consulting" in DEFAULT_COMPANY_BLOCKLISTS
        assert "recruiting_staffing" in DEFAULT_TITLE_BLOCKLISTS
        assert "consulting" in DEFAULT_TITLE_BLOCKLISTS
        assert "hourly_temp" in DEFAULT_TITLE_BLOCKLISTS
