"""
Personalized email and WhatsApp message generation
Uses LLM with personalization plan for targeted outreach
"""

from typing import Optional
from .models import (
    CVProfile,
    JobPosting,
    EmailDraft,
    WhatsAppDraft,
    PersonalizationPlan,
    Project,
)
from .llm import LocalLLMClient
from .prompts import (
    PERSONALIZATION_PLAN_PROMPT,
    EMAIL_DRAFT_PROMPT,
    WHATSAPP_DRAFT_PROMPT,
)


class PersonalizationEngine:
    """Generate personalized outreach messages"""

    def __init__(self, llm_client: LocalLLMClient):
        self.llm = llm_client

    def create_personalization_plan(
        self, cv_profile: CVProfile, job_posting: JobPosting
    ) -> PersonalizationPlan:
        """Create strategic personalization plan"""

        # Prepare CV summary
        projects_text = self._format_projects(cv_profile.projects)
        achievements_text = self._format_achievements(cv_profile.experiences)

        prompt = PERSONALIZATION_PLAN_PROMPT.format(
            candidate_name=cv_profile.name or "Candidate",
            candidate_summary=cv_profile.summary or "Experienced professional",
            projects_text=projects_text,
            achievements_text=achievements_text,
            job_title=job_posting.title,
            company_name=job_posting.company,
            requirements=", ".join(job_posting.requirements[:5]),
            tech_stack=", ".join(job_posting.tech_stack[:5]),
            problems=", ".join(job_posting.problems[:3]),
        )

        try:
            plan_data = self.llm.generate_json(prompt, temperature=0.4)
            plan = PersonalizationPlan(**plan_data)
            return plan
        except Exception as e:
            # Fallback to basic plan
            return self._create_fallback_plan(cv_profile, job_posting)

    def generate_email(
        self,
        cv_profile: CVProfile,
        job_posting: JobPosting,
        recipient_name: Optional[str] = None,
        angle: str = "technical",
    ) -> EmailDraft:
        """Generate personalized email draft"""

        # Create personalization plan
        plan = self.create_personalization_plan(cv_profile, job_posting)

        # Format data for prompt
        anchor_project = self._format_anchor_project(plan.anchor_project)
        metrics = "\n".join(plan.relevant_metrics[:2])

        prompt = EMAIL_DRAFT_PROMPT.format(
            anchor_project=anchor_project,
            technical_hook=plan.technical_hook,
            impact_hook=plan.impact_hook,
            company_hook=plan.company_hook,
            metrics=metrics,
            job_title=job_posting.title,
            company_name=job_posting.company,
            recipient_name=recipient_name or "Hiring Manager",
            angle=angle,
        )

        try:
            email_data = self.llm.generate_json(prompt, temperature=0.6)

            draft = EmailDraft(
                subject=email_data.get("subject", f"Re: {job_posting.title}"),
                body=email_data.get("body", ""),
                recipient_name=recipient_name,
                job_title=job_posting.title,
                company=job_posting.company,
                personalization_plan=plan,
            )

            return draft

        except Exception as e:
            raise Exception(f"Email generation failed: {str(e)}")

    def generate_whatsapp_message(
        self,
        cv_profile: CVProfile,
        job_posting: JobPosting,
        phone: Optional[str] = None,
    ) -> WhatsAppDraft:
        """Generate WhatsApp message with click-to-chat link"""

        # Create personalization plan
        plan = self.create_personalization_plan(cv_profile, job_posting)

        # Get best metric and project
        metric = (
            plan.relevant_metrics[0] if plan.relevant_metrics else "relevant experience"
        )
        project_name = plan.anchor_project.name if plan.anchor_project else "a project"
        project_link = plan.anchor_project.link if plan.anchor_project else ""

        prompt = WHATSAPP_DRAFT_PROMPT.format(
            job_title=job_posting.title,
            company_name=job_posting.company,
            candidate_name=cv_profile.name or "I",
            anchor_project=project_name,
            metric=metric,
            link=project_link,
        )

        try:
            wa_data = self.llm.generate_json(prompt, temperature=0.5)
            message = wa_data.get("message", "")

            # Generate click-to-chat URL
            from .whatsapp import WhatsAppClient

            wa_client = WhatsAppClient()
            url = wa_client.create_click_to_chat_url(message, phone)

            draft = WhatsAppDraft(
                message=message,
                click_to_chat_url=url,
                recipient_phone=phone,
                job_title=job_posting.title,
                company=job_posting.company,
            )

            return draft

        except Exception as e:
            raise Exception(f"WhatsApp message generation failed: {str(e)}")

    def regenerate_email_with_angle(
        self, existing_draft: EmailDraft, angle: str
    ) -> EmailDraft:
        """Regenerate email with different angle"""
        # Use existing personalization plan
        if not existing_draft.personalization_plan:
            raise ValueError("Existing draft must have personalization plan")

        plan = existing_draft.personalization_plan

        anchor_project = self._format_anchor_project(plan.anchor_project)
        metrics = "\n".join(plan.relevant_metrics[:2])

        prompt = EMAIL_DRAFT_PROMPT.format(
            anchor_project=anchor_project,
            technical_hook=plan.technical_hook,
            impact_hook=plan.impact_hook,
            company_hook=plan.company_hook,
            metrics=metrics,
            job_title=existing_draft.job_title,
            company_name=existing_draft.company,
            recipient_name=existing_draft.recipient_name or "Hiring Manager",
            angle=angle,
        )

        email_data = self.llm.generate_json(prompt, temperature=0.7)

        return EmailDraft(
            subject=email_data.get("subject"),
            body=email_data.get("body"),
            recipient_name=existing_draft.recipient_name,
            job_title=existing_draft.job_title,
            company=existing_draft.company,
            personalization_plan=plan,
        )

    def _format_projects(self, projects: list) -> str:
        """Format projects for prompt"""
        if not projects:
            return "No projects listed"

        formatted = []
        for p in projects[:3]:  # Top 3 projects
            proj_str = f"- {p.name}: {p.description}"
            if p.technologies:
                proj_str += f" (Tech: {', '.join(p.technologies[:3])})"
            if p.link or p.github:
                proj_str += f" [Link: {p.link or p.github}]"
            formatted.append(proj_str)

        return "\n".join(formatted)

    def _format_achievements(self, experiences: list) -> str:
        """Format achievements for prompt"""
        if not experiences:
            return "No experience listed"

        formatted = []
        for exp in experiences[:2]:  # Top 2 experiences
            for achievement in exp.achievements[:2]:
                formatted.append(f"- {achievement}")
            for metric in exp.metrics[:2]:
                formatted.append(f"- {metric}")

        return "\n".join(formatted[:5])  # Top 5 total

    def _format_anchor_project(self, project: Optional[Project]) -> str:
        """Format anchor project for prompt"""
        if not project:
            return "No anchor project identified"

        text = f"{project.name}: {project.description}"
        if project.link:
            text += f" [Link: {project.link}]"
        return text

    def _create_fallback_plan(
        self, cv_profile: CVProfile, job_posting: JobPosting
    ) -> PersonalizationPlan:
        """Create basic fallback plan when LLM fails"""

        anchor_project = cv_profile.projects[0] if cv_profile.projects else None

        return PersonalizationPlan(
            anchor_project=anchor_project,
            technical_hook=f"Experience with {', '.join(cv_profile.skills[:3])}",
            impact_hook="Track record of delivering impactful solutions",
            company_hook=f"Interested in {job_posting.title} role",
            shared_technologies=cv_profile.skills[:3],
            relevant_metrics=[],
            angle="technical",
        )
