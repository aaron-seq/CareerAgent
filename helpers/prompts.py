"""
Prompt templates for local LLM (Ollama)
Optimized for llama3, qwen, mistral models
All prompts request JSON outputs for structured parsing
"""

CV_PARSE_PROMPT = """You are an expert CV analyzer. Extract structured information from the CV text below.

CV TEXT:
{cv_text}

Extract and return ONLY valid JSON with this exact structure:
{{
    "name": "Full Name",
    "email": "email@example.com",
    "phone": "+1234567890",
    "linkedin": "linkedin.com/in/username",
    "github": "github.com/username",
    "portfolio": "portfolio-url.com",
    "summary": "Brief summary",
    "experiences": [
        {{
            "title": "Job Title",
            "company": "Company",
            "duration": "Dates",
            "achievements": ["Action result 1", "Action result 2"],
            "metrics": ["Improved X by Y%", "Served N users"],
            "technologies": ["Tech1", "Tech2"]
        }}
    ],
    "projects": [
        {{
            "name": "Project Name",
            "description": "One sentence description",
            "technologies": ["Tech1"],
            "link": "https://url.com",
            "impact": "Metric or scale"
        }}
    ],
    "skills": ["Skill1", "Skill2"],
    "education": ["Degree, Uni, Year"]
}}

RULES:
1. Extract ALL details.
2. Return ONLY valid JSON."""


JOB_PARSE_PROMPT = """You are a job posting analyzer. Extract key structured information.

JOB DESCRIPTION:
{job_text}

JOB URL: {job_url}

Extract and return ONLY valid JSON (no other text):
{{
    "title": "Exact Job Title",
    "company": "Company Name",
    "location": "City, Country or Remote",
    "requirements": ["Must-have requirement 1", "Must-have 2", "Must-have 3"],
    "nice_to_have": ["Preferred skill 1", "Preferred 2"],
    "tech_stack": ["Technology1", "Technology2", "Technology3"],
    "problems": ["Business problem they're solving 1", "Problem 2"],
    "benefits": ["Benefit 1", "Benefit 2"],
    "salary_range": "USD 100K-150K or null if not mentioned"
}}

FOCUS ON:
1. Core technical requirements (languages, frameworks, tools explicitly mentioned)
2. Years of experience if stated
3. Business problems or challenges mentioned
4. What makes this role unique or interesting
5. Actual tech stack, not generic terms

Return ONLY valid JSON."""


PERSONALIZATION_PLAN_PROMPT = """You are a career strategist. Create a personalization plan for outreach.

CANDIDATE PROFILE:
Name: {candidate_name}
Summary: {candidate_summary}

KEY PROJECTS:
{projects_text}

KEY ACHIEVEMENTS:
{achievements_text}

JOB POSTING:
Title: {job_title}
Company: {company_name}
Requirements: {requirements}
Tech Stack: {tech_stack}
Problems: {problems}

Analyze the overlap and create ONLY valid JSON (no other text):
{{
    "anchor_project": {{
        "name": "Most relevant project name from candidate's portfolio",
        "description": "Brief description",
        "link": "URL if available",
        "relevance": "Why this project matches the job"
    }},
    "technical_hook": "1-2 sentences about specific technical alignment (mention exact technologies)",
    "impact_hook": "1-2 sentences about business impact story with metrics",
    "company_hook": "1-2 sentences referencing something specific from the job post or company",
    "shared_technologies": ["Tech1", "Tech2", "Tech3"],
    "relevant_metrics": ["Metric 1 from CV", "Metric 2 from CV"]
}}

RULES:
- Anchor project MUST be real from candidate's CV
- Technical hook MUST reference specific tech stack overlap
- Company hook MUST be derived from job post details
- Metrics MUST be from candidate's actual achievements
- Be specific, not generic

Return ONLY valid JSON."""


EMAIL_DRAFT_PROMPT = """You are a professional email writer. Write a personalized outreach email.

PERSONALIZATION CONTEXT:
Anchor Project: {anchor_project}
Technical Hook: {technical_hook}
Impact Hook: {impact_hook}
Company Hook: {company_hook}
Relevant Metrics: {metrics}

JOB DETAILS:
Title: {job_title}
Company: {company_name}
Recipient Name: {recipient_name}

ANGLE: {angle}
(technical = focus on technical skills, impact = business outcomes, product = product thinking)

Generate email as ONLY valid JSON (no markdown, no extra text):
{{
    "subject": "Subject line under 60 characters, compelling and relevant",
    "body": "Full email body text"
}}

STRICT NON-NEGOTIABLE RULES:
1. NO emojis anywhere (✅ ❌ 🚀 etc.)
2. NO bullet points with dashes (-, •, *, →)
3. NO generic openings like "I hope this email finds you well" or "I'm excited to apply"
4. MUST include at least ONE clickable link (project, GitHub, portfolio)
5. MUST include at least ONE concrete metric with numbers
6. MUST reference something specific from the job post or company
7. Tone: peer-to-peer, confident, direct (not begging or desperate)
8. Call to action: ask for 7-10 minute call or offer to show quick demo
9. Keep under 180 words
10. Use short paragraphs with clear spacing, no bullet lists

STRUCTURE:
Opening: Direct reference to job or company (1 sentence)
Body: One relevant project with metric + technical fit (2-3 sentences)
Close: Clear CTA with easy next step (1 sentence)

Return ONLY valid JSON with subject and body keys."""


WHATSAPP_DRAFT_PROMPT = """Create a WhatsApp message for job outreach. Must be brief and professional.

CONTEXT:
Job: {job_title} at {company_name}
Candidate: {candidate_name}
Anchor Project: {anchor_project}
Key Metric: {metric}
Project Link: {link}

Write message under 300 characters that:
1. States purpose immediately (no "Hi, hope you're well")
2. Mentions ONE relevant project or metric
3. Includes link if available
4. Asks for quick call or meeting
5. NO emojis
6. Professional but conversational

Return ONLY valid JSON:
{{
    "message": "WhatsApp message text"
}}

Example style: "I'm {candidate_name}, built {project} that {metric}. Saw your {job_title} role at {company_name}. Would love a quick 10-min call to discuss fit. Available this week?"

Return ONLY valid JSON."""


CONTACT_SEARCH_QUERIES_PROMPT = """Generate web search queries to find hiring manager or recruiter contact info.

COMPANY: {company_name}
JOB TITLE: {job_title}
ROLE KEYWORDS: {role_keyword}

Generate 5 diverse search queries as JSON array:
[
    "query 1",
    "query 2",
    "query 3",
    "query 4",
    "query 5"
]

Use patterns like:
- "{company_name} engineering manager {role_keyword} email"
- "site:linkedin.com/in {company_name} technical recruiter"
- "{company_name} hiring for {role_keyword} contact"
- "{company_name} people operations team"
- "{company_name} {role_keyword} team lead"

Return ONLY JSON array of 5 queries, no other text."""
