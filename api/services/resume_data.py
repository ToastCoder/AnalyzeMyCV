# AnalyzeMyCV
# api/services/resume_data.py
"""Structured resume: what the model returns, validated and size-capped, and the
Markdown rendering of it. LaTeX rendering lives in latex_templates.py. Everything
the model writes passes through these models, so downstream renderers only ever
see bounded, control-character-free text."""

import json
import re
import unicodedata
from typing import List
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator


def _clean(value) -> str:
    """Single-line text: NFKC, no control/format characters, collapsed whitespace."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = "".join(c if c not in "\n\r\t" else " " for c in text if c in "\n\r\t" or not unicodedata.category(c).startswith("C"))
    return re.sub(r"\s+", " ", text).strip()


def _clean_bullet(value) -> str:
    return re.sub(r"^[\s\-•‣◦⁃∙*·]+", "", _clean(value))


class _Model(BaseModel):
    # Unknown keys from the model are dropped rather than rejected.
    model_config = {"extra": "ignore"}


class Link(_Model):
    label: str = Field("", max_length=40)
    url: str = Field("", max_length=200)

    @field_validator("label", mode="before")
    @classmethod
    def _label(cls, v):
        return _clean(v)

    @field_validator("url", mode="before")
    @classmethod
    def _url(cls, v):
        """Only http(s) links survive; a bare domain gets https://. Anything else becomes empty."""
        url = _clean(v)
        if not url:
            return ""
        if "://" not in url:
            url = "https://" + url
        parsed = urlparse(url)
        host = parsed.hostname or ""
        # A real host has a dot: this also rejects `javascript:...` and similar, which otherwise
        # become "https://javascript:...".
        # No credentials in the URL (`https://google.com@evil.com` is a classic disguise).
        if parsed.username or parsed.password or "@" in parsed.netloc:
            return ""
        if parsed.scheme not in ("http", "https") or " " in url or not re.fullmatch(r"[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+", host):
            return ""
        return url


class Entry(_Model):
    title: str = Field("", max_length=140)        # role, degree or project name
    organization: str = Field("", max_length=140)  # employer or school
    location: str = Field("", max_length=100)
    dates: str = Field("", max_length=60)
    bullets: List[str] = Field(default_factory=list, max_length=12)

    @field_validator("title", "organization", "location", "dates", mode="before")
    @classmethod
    def _text(cls, v):
        return _clean(v)

    @field_validator("bullets", mode="before")
    @classmethod
    def _bullets(cls, v):
        items = [_clean_bullet(b) for b in (v or [])]
        return [b[:400] for b in items if b][:12]


class SkillRow(_Model):
    label: str = Field("", max_length=60)
    items: str = Field("", max_length=300)

    @field_validator("label", "items", mode="before")
    @classmethod
    def _text(cls, v):
        return _clean(v)


class Section(_Model):
    title: str = Field("", max_length=60)
    entries: List[Entry] = Field(default_factory=list, max_length=15)
    skills: List[SkillRow] = Field(default_factory=list, max_length=12)
    text: str = Field("", max_length=1500)

    @field_validator("title", "text", mode="before")
    @classmethod
    def _text(cls, v):
        return _clean(v)

    @field_validator("entries", mode="before")
    @classmethod
    def _entries(cls, v):
        return (v or [])[:15]

    @field_validator("skills", mode="before")
    @classmethod
    def _skills(cls, v):
        return (v or [])[:12]

    def is_empty(self) -> bool:
        return not (self.entries or self.skills or self.text)


class Resume(_Model):
    name: str = Field("", max_length=100)
    headline: str = Field("", max_length=150)
    email: str = Field("", max_length=100)
    phone: str = Field("", max_length=40)
    location: str = Field("", max_length=100)
    links: List[Link] = Field(default_factory=list, max_length=6)
    summary: str = Field("", max_length=1500)
    sections: List[Section] = Field(default_factory=list, max_length=12)
    # Advice for the candidate (what changed, requirement gaps); shown in the UI, never in a resume.
    notes: List[str] = Field(default_factory=list, max_length=9)

    @field_validator("notes", mode="before")
    @classmethod
    def _notes(cls, v):
        return [n[:200] for n in (_clean(x) for x in (v or [])[:9]) if n]

    @field_validator("name", "headline", "phone", "location", "summary", mode="before")
    @classmethod
    def _text(cls, v):
        return _clean(v)

    @field_validator("email", mode="before")
    @classmethod
    def _email(cls, v):
        email = _clean(v)
        return email if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) else ""

    @field_validator("links", mode="before")
    @classmethod
    def _links(cls, v):
        return (v or [])[:6]

    @field_validator("sections", mode="before")
    @classmethod
    def _sections(cls, v):
        return (v or [])[:12]

    def model_post_init(self, _ctx) -> None:
        self.links = [link for link in self.links if link.url]
        self.sections = [s for s in self.sections if s.title and not s.is_empty()]


def parse_resume_json(raw: str) -> Resume:
    """Parse the model's reply (optionally wrapped in a code fence) into a Resume.
    Raises ValueError if it isn't usable."""
    text = (raw or "").strip()
    fenced = re.fullmatch(r"```(?:json)?\s*\n(.*?)\n```", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(1)
    try:
        resume = Resume.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValueError) as e:
        raise ValueError(f"model reply is not a valid resume: {type(e).__name__}") from e
    if not resume.name or not (resume.sections or resume.summary):
        raise ValueError("model reply has no name or no content")
    return resume


def contact_items(resume: Resume) -> List[str]:
    return [x for x in (resume.email, resume.phone, resume.location) if x] + [
        link.label or link.url for link in resume.links
    ]


_MD_ACTIVE = re.compile(r"([\\`\[\]<>])")


def md_escape(text: str) -> str:
    """Neutralize Markdown that could fetch or link anything: `![x](https://host/?q=...)` would be
    rendered as an image the browser loads without a click. Model-written text is data, never markup."""
    return _MD_ACTIVE.sub(r"\\\1", text)


def to_markdown(resume: Resume) -> str:
    """Readable Markdown of the same content: `#` name, `##` sections, bold role lines."""
    lines: List[str] = [f"# {md_escape(resume.name)}", ""]
    if resume.headline:
        lines += [f"*{md_escape(resume.headline)}*", ""]
    contact = contact_items(resume)
    if contact:
        lines += [" | ".join(md_escape(c) for c in contact), ""]
    if resume.summary:
        lines += ["## Summary", "", md_escape(resume.summary), ""]
    for section in resume.sections:
        lines += [f"## {md_escape(section.title)}", ""]
        if section.text:
            lines += [md_escape(section.text), ""]
        for row in section.skills:
            lines.append(f"- **{md_escape(row.label)}:** {md_escape(row.items)}" if row.label else f"- {md_escape(row.items)}")
        if section.skills:
            lines.append("")
        for e in section.entries:
            head = ", ".join(md_escape(x) for x in (e.title, e.organization, e.location) if x)
            if e.dates:
                head = f"{head} ({md_escape(e.dates)})" if head else md_escape(e.dates)
            lines.append(f"**{head}**" if head else "")
            lines += [f"- {md_escape(b)}" for b in e.bullets]
            lines.append("")
    return "\n".join(lines).strip() + "\n"
