"""Tests for the job_filter module."""

import pytest

from src.job_filter import filter_job, is_relevant_title, is_excluded_company


class TestIsRelevantTitle:
    def test_positive_match_compliance(self):
        assert is_relevant_title("Compliance Analyst") is True

    def test_positive_match_risk(self):
        assert is_relevant_title("Risk Manager") is True

    def test_positive_match_audit(self):
        assert is_relevant_title("Internal Audit Specialist") is True

    def test_positive_match_fraud(self):
        assert is_relevant_title("Fraud Investigator") is True

    def test_negative_match_software(self):
        assert is_relevant_title("Software Engineer") is False

    def test_negative_match_sales(self):
        assert is_relevant_title("Sales Manager") is False

    def test_no_match_generic(self):
        assert is_relevant_title("Product Manager") is False

    def test_case_insensitive(self):
        assert is_relevant_title("COMPLIANCE ANALYST") is True

    def test_too_senior_director(self):
        assert is_relevant_title("Director of Compliance") is False

    def test_too_senior_vp(self):
        assert is_relevant_title("VP Risk Management") is False

    def test_compound_positive(self):
        assert is_relevant_title("Compliance Specialist") is True

    def test_analyst_alone_no_match(self):
        # "analyst" alone is NOT in positive list (too broad)
        assert is_relevant_title("Financial Analyst") is False

    def test_data_analyst_match(self):
        assert is_relevant_title("Data Analyst") is True

    def test_bsa_aml_match(self):
        assert is_relevant_title("BSA/AML Officer") is True

    def test_governance_match(self):
        assert is_relevant_title("Governance Coordinator") is True

    def test_examiner_match(self):
        assert is_relevant_title("Bank Examiner") is True

    def test_monitoring_match(self):
        assert is_relevant_title("Transaction Monitoring Analyst") is True

    def test_negative_recruiter(self):
        assert is_relevant_title("Recruiter") is False

    def test_negative_cpa(self):
        assert is_relevant_title("CPA Accountant") is False

    def test_too_senior_svp(self):
        assert is_relevant_title("SVP Compliance") is False

    def test_too_senior_head_of(self):
        assert is_relevant_title("Head of Risk") is False


class TestIsExcludedCompany:
    def test_excluded_pge(self):
        assert is_excluded_company("PG&E") is True

    def test_excluded_pacific_gas(self):
        assert is_excluded_company("Pacific Gas and Electric Company") is True

    def test_not_excluded(self):
        assert is_excluded_company("Google") is False

    def test_excluded_case_insensitive(self):
        assert is_excluded_company("pg&e") is True

    def test_not_excluded_partial(self):
        assert is_excluded_company("Acme Corp") is False


class TestFilterJob:
    def test_passes_good_job(self):
        passes, reason = filter_job({"title": "Compliance Analyst", "company": "Acme"})
        assert passes is True
        assert reason == ""

    def test_rejects_excluded_company(self):
        passes, reason = filter_job({"title": "Compliance Analyst", "company": "PG&E"})
        assert passes is False
        assert "excluded_company" in reason

    def test_rejects_irrelevant_title(self):
        passes, reason = filter_job({"title": "Software Engineer", "company": "Acme"})
        assert passes is False
        assert "irrelevant_title" in reason

    def test_handles_newline_in_title(self):
        passes, reason = filter_job({
            "title": "Compliance Analyst\nCompliance Analyst",
            "company": "Acme",
        })
        assert passes is True

    def test_empty_title_rejected(self):
        passes, reason = filter_job({"title": "", "company": "Acme"})
        assert passes is False

    def test_empty_company_not_excluded(self):
        passes, reason = filter_job({"title": "Risk Analyst", "company": ""})
        assert passes is True

    def test_missing_keys_handled(self):
        passes, reason = filter_job({})
        assert passes is False

    def test_excluded_company_takes_priority(self):
        """Even with a relevant title, excluded company should reject."""
        passes, reason = filter_job({
            "title": "Compliance Manager",
            "company": "Pacific Gas and Electric",
        })
        assert passes is False
        assert "excluded_company" in reason
