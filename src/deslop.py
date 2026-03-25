"""De-slop filter — removes AI tells from generated documents."""

from pathlib import Path
from docx import Document


# AI giveaway patterns → human replacements
REPLACEMENTS = {
    " — ": ", ",
    " – ": ", ",
    "I'm excited to": "I'd like to",
    "I am excited to": "I'd like to",
    "I'm thrilled to": "I'm writing to",
    "Great question": "",
    "I'd be happy to": "",
    "leverage my": "use my",
    "leveraging": "using",
    "Leverage": "Use",
    "synergy": "alignment",
    "synergies": "connections",
    "utilize": "use",
    "utilization": "use",
}


def clean_text(text: str) -> str:
    """Apply all de-slop replacements to a string."""
    for old, new in REPLACEMENTS.items():
        text = text.replace(old, new)
    return text


def clean_docx(path: str | Path) -> Path:
    """Clean AI tells from a .docx file in-place."""
    path = Path(path)
    if not path.exists():
        return path

    doc = Document(str(path))
    changed = False

    for paragraph in doc.paragraphs:
        for run in paragraph.runs:
            cleaned = clean_text(run.text)
            if cleaned != run.text:
                run.text = cleaned
                changed = True

    if changed:
        doc.save(str(path))

    return path


def clean_directory(dir_path: str | Path):
    """Clean all .docx files in a directory."""
    dir_path = Path(dir_path)
    for docx_file in dir_path.glob("**/*.docx"):
        clean_docx(docx_file)
