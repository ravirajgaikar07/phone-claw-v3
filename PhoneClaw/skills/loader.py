"""Skills loader — scan, parse, and inject SKILL.md files into prompts."""

import os
import re
from pathlib import Path

import config
from utils.logger import get_logger

log = get_logger("skills.loader")

_skills_cache = None


def load_skills(skills_dir=None):
    """Scan the skills directory and return parsed skill entries.

    Each skill is a subdirectory containing a SKILL.md file.
    Returns list of skill dicts: {name, description, requires, content, eligible}.
    """
    global _skills_cache
    if _skills_cache is not None:
        return _skills_cache

    if skills_dir is None:
        skills_dir = Path(__file__).parent

    skills_dir = Path(skills_dir)
    if not skills_dir.is_dir():
        log.warning("Skills directory not found: %s", skills_dir)
        _skills_cache = []
        return _skills_cache

    skills = []
    for entry in sorted(skills_dir.iterdir()):
        if not entry.is_dir():
            continue
        skill_file = entry / "SKILL.md"
        if not skill_file.exists():
            continue

        skill = _parse_skill_md(skill_file, entry.name)
        if skill:
            skill["eligible"] = _check_requirements(skill.get("requires", {}))
            skills.append(skill)
            log.debug("Loaded skill: %s (eligible=%s)", skill["name"], skill["eligible"])

    _skills_cache = skills
    log.info("Loaded %d skills (%d eligible)",
             len(skills), sum(1 for s in skills if s["eligible"]))
    return _skills_cache


def reload_skills():
    """Force reload skills from disk."""
    global _skills_cache
    _skills_cache = None
    return load_skills()


def _parse_skill_md(path, dir_name):
    """Parse a SKILL.md file with YAML frontmatter + markdown body."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        log.warning("Failed to read %s: %s", path, exc)
        return None

    # Extract YAML frontmatter between --- markers
    frontmatter = {}
    body = text
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
    if fm_match:
        fm_text = fm_match.group(1)
        body = fm_match.group(2).strip()
        # Simple YAML-like parsing (no PyYAML dependency)
        for line in fm_text.split("\n"):
            line = line.strip()
            if ":" in line and not line.startswith("#"):
                key, _, val = line.partition(":")
                frontmatter[key.strip()] = val.strip().strip('"').strip("'")

    return {
        "name": frontmatter.get("name", dir_name),
        "description": frontmatter.get("description", ""),
        "requires": _parse_requires(frontmatter),
        "content": body,
        "path": str(path),
    }


def _parse_requires(frontmatter):
    """Parse requirement fields from frontmatter."""
    requires = {}
    for key, val in frontmatter.items():
        if key.startswith("requires."):
            req_type = key.split(".", 1)[1]
            requires[req_type] = [v.strip() for v in val.split(",")]
    return requires


def _check_requirements(requires):
    """Check if skill requirements are met."""
    if not requires:
        return True

    # Check environment variables
    for env_var in requires.get("env", []):
        if not os.environ.get(env_var):
            log.debug("Skill requires env var %s (not set)", env_var)
            return False

    # Check binaries on PATH
    for binary in requires.get("bins", []):
        if not _has_binary(binary):
            log.debug("Skill requires binary %s (not found)", binary)
            return False

    return True


def _has_binary(name):
    """Check if a binary exists on PATH."""
    import shutil
    return shutil.which(name) is not None


def build_skills_prompt(max_chars=3000):
    """Build the skills section for the system prompt.

    Budget-aware: skips content if total would exceed max_chars.
    """
    skills = load_skills()
    eligible = [s for s in skills if s["eligible"]]
    if not eligible:
        return ""

    parts = ["# Available Skills"]
    total = len(parts[0])

    for skill in eligible:
        header = f"\n## {skill['name']}"
        if skill["description"]:
            header += f"\n{skill['description']}"

        entry = header + "\n" + skill["content"]

        if total + len(entry) > max_chars:
            # Budget exceeded — add name-only listing for remaining
            remaining = [s["name"] for s in eligible if s["name"] not in
                         "".join(parts)]
            if remaining:
                parts.append(f"\n(+{len(remaining)} more skills available)")
            break

        parts.append(entry)
        total += len(entry)

    return "\n".join(parts)


def list_skill_info():
    """Return skill info for display (name, description, eligible)."""
    skills = load_skills()
    return [
        {
            "name": s["name"],
            "description": s["description"],
            "eligible": s["eligible"],
        }
        for s in skills
    ]
