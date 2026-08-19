"""Build GitHub Release notes from one exact CHANGELOG.md section."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path


SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
RELEASE_HEADING_RE = re.compile(r"^## \[([^]]+)](?:\s+-\s+.*)?\s*$")


def parse_stable_version(value):
    match = SEMVER_RE.fullmatch(value)
    if match is None:
        return None
    return tuple(int(part) for part in match.groups())


def extract_changelog_section(changelog, version):
    """Return only the Markdown below the requested release heading."""
    expected = re.compile(rf"^## \[{re.escape(version)}]\s+-\s+.+\s*$")
    lines = changelog.splitlines(keepends=True)
    start = None
    for index, line in enumerate(lines):
        if expected.fullmatch(line.rstrip("\r\n")):
            start = index + 1
            break
    if start is None:
        raise ValueError(
            f"CHANGELOG.md has no release section for expected version {version}"
        )
    end = len(lines)
    for index in range(start, len(lines)):
        if RELEASE_HEADING_RE.fullmatch(lines[index].rstrip("\r\n")):
            end = index
            break
    section = "".join(lines[start:end]).strip()
    if not section:
        raise ValueError(
            f"CHANGELOG.md release section for version {version} is empty"
        )
    return section


def find_previous_stable_tag(current_tag, tags):
    """Choose the greatest reachable stable SemVer tag below current_tag."""
    current = parse_stable_version(current_tag)
    if current is None:
        raise ValueError(f"Current tag is not a stable semantic version: {current_tag}")
    candidates = []
    for tag in tags:
        parsed = parse_stable_version(tag)
        if parsed is not None and parsed < current:
            candidates.append((parsed, f"v{parsed[0]}.{parsed[1]}.{parsed[2]}"))
    return max(candidates)[1] if candidates else None


def build_release_body(section, sha256, installer_name, repository, current_tag, previous_tag=None):
    if SHA256_RE.fullmatch(sha256) is None:
        raise ValueError("SHA-256 must contain exactly 64 hexadecimal characters")
    if Path(installer_name).name != installer_name:
        raise ValueError("Installer name must be a plain filename")
    if REPOSITORY_RE.fullmatch(repository) is None:
        raise ValueError(f"Invalid GitHub repository name: {repository}")
    if parse_stable_version(current_tag) is None:
        raise ValueError(f"Current tag is not a stable semantic version: {current_tag}")
    body = (
        section.rstrip()
        + "\n\n## SHA-256\n\n"
        + f"`{sha256.lower()}` — `{installer_name}`"
    )
    if previous_tag is not None:
        if parse_stable_version(previous_tag) is None:
            raise ValueError(f"Previous tag is not a stable semantic version: {previous_tag}")
        body += (
            "\n\n**Full Changelog:** "
            f"https://github.com/{repository}/compare/{previous_tag}...{current_tag}"
        )
    return body + "\n"


def reachable_tags():
    result = subprocess.run(
        ["git", "tag", "--merged", "HEAD", "--list", "v*"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--changelog", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--installer-name", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--current-tag", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    expected_tag = f"v{args.version}"
    if args.current_tag != expected_tag:
        raise SystemExit(
            f"Current tag {args.current_tag} does not match expected tag {expected_tag}"
        )
    try:
        section = extract_changelog_section(
            args.changelog.read_text(encoding="utf-8"), args.version
        )
        previous_tag = find_previous_stable_tag(args.current_tag, reachable_tags())
        body = build_release_body(
            section,
            args.sha256,
            args.installer_name,
            args.repository,
            args.current_tag,
            previous_tag,
        )
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise SystemExit(f"Release notes generation failed: {exc}") from exc
    args.output.write_text(body, encoding="utf-8", newline="\n")
    print(f"Release notes written to {args.output}")
    if previous_tag is None:
        print("No earlier reachable stable SemVer tag found; compare link omitted.")
    else:
        print(f"Previous release tag: {previous_tag}")


if __name__ == "__main__":
    main()
