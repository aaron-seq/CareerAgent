"""Tests for PersonalizationEngine (LLM-driven outreach draft generation)

The LLM is mocked per CLAUDE.md -- no live network calls in the checked-in
suite. Live testing this session (not checked in) found
`generate_whatsapp_message` always raised `KeyError: 'project'` because
WHATSAPP_DRAFT_PROMPT's example line references {project} while the format
call only supplied {anchor_project}; see the regression test below.
"""

from unittest.mock import Mock

import pytest

from core.models import CVProfile, Experience, JobPosting, Project
from core.personalization import PersonalizationEngine


def _cv():
    return CVProfile(
        name="Alex Rivera",
        summary="Backend engineer focused on distributed systems.",
        experiences=[
            Experience(
                title="Senior Backend Engineer",
                company="DataFlow Inc",
                duration="2022-2026",
                achievements=["Led migration to Kafka"],
                metrics=["Reduced infra cost by 30%"],
                technologies=["Python", "Kafka"],
            )
        ],
        projects=[
            Project(
                name="OpenPipe",
                description="Open-source ETL orchestration framework",
                technologies=["Python"],
                link="https://github.com/alexrivera/openpipe",
            )
        ],
        skills=["Python", "Kafka", "Postgres"],
    )


def _job():
    return JobPosting(
        title="Staff Backend Engineer",
        company="Anthropic",
        requirements=["Python", "distributed systems"],
        tech_stack=["Python", "Kafka"],
        problems=["Scaling data pipelines"],
    )


def _plan_json():
    return {
        "anchor_project": {
            "name": "OpenPipe",
            "description": "Open-source ETL orchestration framework",
            "link": "https://github.com/alexrivera/openpipe",
        },
        "technical_hook": "Python and Kafka experience matches your stack.",
        "impact_hook": "Cut p99 latency by 40%.",
        "company_hook": "Saw you're scaling data pipelines.",
        "shared_technologies": ["Python", "Kafka"],
        "relevant_metrics": ["Reduced infra cost by 30%"],
    }


class TestCreatePersonalizationPlan:
    def test_builds_plan_from_llm_json(self):
        llm = Mock()
        llm.generate_json.return_value = _plan_json()
        engine = PersonalizationEngine(llm)
        plan = engine.create_personalization_plan(_cv(), _job())
        assert plan.anchor_project.name == "OpenPipe"
        assert plan.technical_hook == "Python and Kafka experience matches your stack."
        assert plan.shared_technologies == ["Python", "Kafka"]

    def test_falls_back_when_llm_fails(self):
        llm = Mock()
        llm.generate_json.side_effect = Exception("LLM down")
        engine = PersonalizationEngine(llm)
        plan = engine.create_personalization_plan(_cv(), _job())
        assert plan.anchor_project.name == "OpenPipe"  # first project in CV
        assert "Python" in plan.technical_hook
        assert plan.angle == "technical"

    def test_fallback_plan_with_no_projects_or_skills(self):
        llm = Mock()
        llm.generate_json.side_effect = Exception("LLM down")
        engine = PersonalizationEngine(llm)
        empty_cv = CVProfile(name="No Projects")
        plan = engine.create_personalization_plan(empty_cv, _job())
        assert plan.anchor_project is None


class TestGenerateEmail:
    def test_generates_draft_with_plan_attached(self):
        llm = Mock()
        llm.generate_json.side_effect = [
            _plan_json(),
            {
                "subject": "Staff Backend Engineer role",
                "body": "Hi, I built OpenPipe...",
            },
        ]
        engine = PersonalizationEngine(llm)
        draft = engine.generate_email(
            _cv(), _job(), recipient_name="Jordan", angle="technical"
        )
        assert draft.subject == "Staff Backend Engineer role"
        assert draft.recipient_name == "Jordan"
        assert draft.company == "Anthropic"
        assert draft.personalization_plan is not None
        assert draft.word_count > 0

    def test_defaults_recipient_to_hiring_manager_in_prompt(self):
        llm = Mock()
        llm.generate_json.side_effect = [
            _plan_json(),
            {"subject": "Subj", "body": "Body"},
        ]
        engine = PersonalizationEngine(llm)
        draft = engine.generate_email(_cv(), _job())
        assert draft.recipient_name is None
        # The prompt sent to generate the email defaulted the placeholder.
        email_prompt = llm.generate_json.call_args_list[1][0][0]
        assert "Hiring Manager" in email_prompt

    def test_raises_on_email_generation_failure(self):
        llm = Mock()
        llm.generate_json.side_effect = [_plan_json(), Exception("LLM down")]
        engine = PersonalizationEngine(llm)
        with pytest.raises(Exception, match="Email generation failed"):
            engine.generate_email(_cv(), _job())


class TestGenerateWhatsappMessage:
    def test_generates_message_without_key_error(self):
        """Regression test: the prompt template previously raised
        KeyError: 'project' before this call ever reached the LLM."""
        llm = Mock()
        llm.generate_json.side_effect = [
            _plan_json(),
            {"message": "Hi, I'm Alex, built OpenPipe. Free for a quick call?"},
        ]
        engine = PersonalizationEngine(llm)
        draft = engine.generate_whatsapp_message(_cv(), _job(), phone="14155551234")
        assert draft.message.startswith("Hi, I'm Alex")
        assert draft.click_to_chat_url.startswith("https://wa.me/14155551234")
        assert draft.character_count == len(draft.message)

    def test_works_without_phone_number(self):
        llm = Mock()
        llm.generate_json.side_effect = [_plan_json(), {"message": "Hello there"}]
        engine = PersonalizationEngine(llm)
        draft = engine.generate_whatsapp_message(_cv(), _job())
        assert draft.click_to_chat_url.startswith("https://wa.me?text=")

    def test_raises_on_whatsapp_generation_failure(self):
        llm = Mock()
        llm.generate_json.side_effect = [_plan_json(), Exception("LLM down")]
        engine = PersonalizationEngine(llm)
        with pytest.raises(Exception, match="WhatsApp message generation failed"):
            engine.generate_whatsapp_message(_cv(), _job())

    def test_handles_missing_anchor_project(self):
        llm = Mock()
        no_project_plan = _plan_json()
        no_project_plan["anchor_project"] = None
        llm.generate_json.side_effect = [
            no_project_plan,
            {"message": "Hello"},
        ]
        engine = PersonalizationEngine(llm)
        draft = engine.generate_whatsapp_message(_cv(), _job())
        assert draft.message == "Hello"


class TestRegenerateEmailWithAngle:
    def test_raises_without_existing_plan(self):
        llm = Mock()
        engine = PersonalizationEngine(llm)
        from core.models import EmailDraft

        draft = EmailDraft(subject="S", body="B", job_title="Engineer", company="Acme")
        with pytest.raises(ValueError, match="personalization plan"):
            engine.regenerate_email_with_angle(draft, "impact")

    def test_reuses_existing_plan(self):
        llm = Mock()
        llm.generate_json.side_effect = [_plan_json(), {"subject": "S1", "body": "B1"}]
        engine = PersonalizationEngine(llm)
        first = engine.generate_email(_cv(), _job(), recipient_name="Jordan")

        llm.generate_json.side_effect = [{"subject": "S2", "body": "B2"}]
        second = engine.regenerate_email_with_angle(first, "impact")
        assert second.subject == "S2"
        assert second.personalization_plan == first.personalization_plan
        assert second.recipient_name == "Jordan"


class TestFormattingHelpers:
    def test_format_projects_empty(self):
        engine = PersonalizationEngine(Mock())
        assert engine._format_projects([]) == "No projects listed"

    def test_format_projects_includes_tech_and_link(self):
        engine = PersonalizationEngine(Mock())
        text = engine._format_projects(_cv().projects)
        assert "OpenPipe" in text
        assert "Python" in text
        assert "github.com/alexrivera/openpipe" in text

    def test_format_achievements_empty(self):
        engine = PersonalizationEngine(Mock())
        assert engine._format_achievements([]) == "No experience listed"

    def test_format_anchor_project_none(self):
        engine = PersonalizationEngine(Mock())
        assert engine._format_anchor_project(None) == "No anchor project identified"
