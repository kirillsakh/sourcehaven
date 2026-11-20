"""Generate the fictional demo documents in ``docs/demo/``.

The person, the companies and the contact details are invented; ``example.com`` is a domain
reserved for examples. Run with ``uv run python scripts/generate_demo_documents.py``. Output is
byte-for-byte deterministic, so regenerating changes nothing unless the text below changes.
"""

from pathlib import Path

from reportlab.lib.colors import Color, HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, ListFlowable, Paragraph, SimpleDocTemplate

DEMO_DIR: Path = Path(__file__).resolve().parent.parent / "docs" / "demo"
INK: Color = HexColor("#1D2433")
ACCENT: Color = HexColor("#1F4E8C")
MUTED: Color = HexColor("#4A5263")
# Typographic dash for date ranges and titles, spelled out so it is not mistaken for a hyphen.
EN_DASH: str = "\u2013"

TITLE: ParagraphStyle = ParagraphStyle(
    "title", fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=INK, spaceAfter=2
)
SUBTITLE: ParagraphStyle = ParagraphStyle(
    "subtitle", fontName="Helvetica", fontSize=10.5, leading=14, textColor=MUTED, spaceAfter=10
)
HEADING: ParagraphStyle = ParagraphStyle(
    "heading",
    fontName="Helvetica-Bold",
    fontSize=12,
    leading=15,
    textColor=ACCENT,
    spaceBefore=10,
    spaceAfter=4,
)
ROLE: ParagraphStyle = ParagraphStyle(
    "role", fontName="Helvetica-Bold", fontSize=10.5, leading=14, textColor=INK, spaceBefore=6
)
BODY: ParagraphStyle = ParagraphStyle(
    "body", fontName="Helvetica", fontSize=10.5, leading=14.5, textColor=INK, spaceAfter=3
)


def bullets(*items: str) -> ListFlowable:
    return ListFlowable(
        [Paragraph(item, BODY) for item in items],
        bulletType="bullet",
        bulletFontSize=7,
        leftIndent=12,
        bulletOffsetY=-1,
    )


def numbered(*items: str) -> ListFlowable:
    return ListFlowable(
        [Paragraph(item, BODY) for item in items],
        bulletType="1",
        bulletFontName="Helvetica",
        bulletFontSize=10,
        leftIndent=16,
    )


CV: list[Flowable] = [
    Paragraph("Alex Novák", TITLE),
    Paragraph(
        "Senior Python Developer · Prague, Czech Republic · alex.novak@example.com", SUBTITLE
    ),
    Paragraph("Summary", HEADING),
    Paragraph(
        "Backend engineer with 8 years of Python, focused on search, data pipelines and APIs. "
        "Recently built retrieval features on PostgreSQL and pgvector and a first LLM-based "
        "assistant for internal documents.",
        BODY,
    ),
    Paragraph("Experience", HEADING),
    Paragraph(f"Larkspur Data, Prague · Senior Python Developer · 03/2022 {EN_DASH} present", ROLE),
    bullets(
        "Built FastAPI services for full-text and semantic document search used by 40 "
        "enterprise customers.",
        "Moved vector search from Elasticsearch to PostgreSQL with pgvector, cutting p95 latency "
        "by 40%.",
        "Prototyped a retrieval-augmented assistant for internal documentation (OpenAI API, "
        "LangChain).",
        "Mentors three engineers; leads the on-call rotation.",
    ),
    Paragraph(f"Kestrel Mobility, Brno · Python Developer · 06/2019 {EN_DASH} 02/2022", ROLE),
    bullets(
        "Django REST APIs for fleet telemetry; Celery pipelines processing 2 million events a day.",
        "Ran services on AWS (ECS, RDS) with infrastructure in Terraform.",
    ),
    Paragraph(f"Orbit Grocer, Prague · Junior Backend Developer · 09/2017 {EN_DASH} 05/2019", ROLE),
    bullets("Flask APIs for the online shop; introduced pytest and code review to the team."),
    Paragraph(f"Brightline Studio, Prague · Intern · 07/2016 {EN_DASH} 08/2017", ROLE),
    bullets("Data collection scripts and reporting in Python."),
    Paragraph("Skills", HEADING),
    bullets(
        "<b>Python:</b> FastAPI, Django, Flask, Celery, pytest, mypy",
        "<b>Data:</b> PostgreSQL (query tuning), pgvector, Redis, Elasticsearch",
        "<b>Ops:</b> Docker, Docker Compose, AWS ECS, Terraform, GitHub Actions",
        "<b>AI:</b> OpenAI API, LangChain, embeddings, prompt design",
        "<b>Languages:</b> Czech (native), English (C1)",
    ),
    Paragraph("Education and certification", HEADING),
    Paragraph("MSc Computer Science, Czech Technical University in Prague, 2017", BODY),
    Paragraph(f"AWS Certified Developer {EN_DASH} Associate, 2021", BODY),
]

JOB_AD: list[Flowable] = [
    Paragraph("Senior Python Engineer (AI)", TITLE),
    Paragraph("Sourcehaven.ai · Prague, hybrid (two office days a week)", SUBTITLE),
    Paragraph("About us", HEADING),
    Paragraph(
        "Sourcehaven.ai helps teams ask questions about their own documents and get answers "
        "with cited sources. We are a team of 12, profitable, and growing our engineering team.",
        BODY,
    ),
    Paragraph("What you will do", HEADING),
    bullets(
        "Design and build the retrieval and answering pipeline: ingestion, chunking, "
        "embeddings, search and generation.",
        "Own services end to end, from API design to running them in production.",
        "Measure answer quality and improve it with evaluations, not guesswork.",
        "Help shape engineering practices and mentor colleagues.",
    ),
    Paragraph("Must-haves", HEADING),
    numbered(
        "5+ years of professional Python development.",
        "Production experience with FastAPI or Django.",
        "Strong PostgreSQL skills, including query performance tuning.",
        "Hands-on work with LLM APIs or retrieval-augmented generation.",
        "A testing habit: pytest, CI, code review.",
        "Running services on Kubernetes in production.",
        "English at B2 level or higher.",
    ),
    Paragraph("Nice-to-haves", HEADING),
    Paragraph(
        "Vector search (pgvector or a dedicated vector database), Terraform, mentoring "
        "experience, Czech.",
        BODY,
    ),
    Paragraph("We offer", HEADING),
    bullets(
        f"CZK 110,000{EN_DASH}140,000 a month.",
        "25 days of holiday.",
        "A learning budget of CZK 30,000 a year.",
        "A MacBook Pro.",
    ),
    Paragraph("Hiring process", HEADING),
    Paragraph(
        "A 30-minute intro call, a take-home task (about 3 hours, paid), then a final interview "
        "with the team. You get a decision within 5 working days.",
        BODY,
    ),
]

INTERVIEW_GUIDE: list[Flowable] = [
    Paragraph("Interview guide", TITLE),
    Paragraph("Sourcehaven.ai · Senior Python Engineer (AI)", SUBTITLE),
    Paragraph("Scorecard", HEADING),
    bullets(
        "System design: 30%",
        "Python depth: 30%",
        "Retrieval and LLM experience: 20%",
        "Collaboration: 20%",
    ),
    Paragraph("Stages", HEADING),
    numbered(
        "Intro call (recruiter): motivation, salary expectations, notice period.",
        "Take-home review: code quality, tests, and trade-offs explained in the README.",
        "Team interview: design a document Q&amp;A service; discuss failure modes and evaluation.",
    ),
    Paragraph("Signals to look for", HEADING),
    bullets(
        "Explains trade-offs clearly.",
        "Tests before optimising.",
        "Asks how answer quality is measured.",
    ),
    Paragraph("Red flags", HEADING),
    bullets(
        "Cannot explain their own take-home.",
        "Dismisses testing.",
        "Overstates LLM experience.",
    ),
    Paragraph("Decision", HEADING),
    Paragraph(
        "The panel scores independently before discussing; the hiring manager decides within "
        "5 working days.",
        BODY,
    ),
]

DOCUMENTS: dict[str, list[Flowable]] = {
    f"Alex Novák {EN_DASH} CV.pdf": CV,
    f"Senior Python Engineer (AI) {EN_DASH} Sourcehaven.ai.pdf": JOB_AD,
    f"Interview guide {EN_DASH} Sourcehaven.ai.pdf": INTERVIEW_GUIDE,
}


def render(path: Path, story: list[Flowable]) -> None:
    """Write one deterministic A4 PDF from a story of flowables.

    Args:
        path: Destination file, overwritten if present.
        story: The document's content in reading order.
    """
    document: SimpleDocTemplate = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=22 * mm,
        rightMargin=22 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        title=path.stem,
        author="Sourcehaven demo (fictional)",
        subject="Fictional demo document",
        invariant=1,
    )
    document.build(list(story))


def main() -> None:
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    for name, story in DOCUMENTS.items():
        render(DEMO_DIR / name, story)


if __name__ == "__main__":
    main()
