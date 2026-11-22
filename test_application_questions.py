import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import application_questions


class ApplicantContextTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.docs = Path(directory.name)
        docs_patch = patch.object(application_questions, "DOCS", self.docs)
        docs_patch.start()
        self.addCleanup(docs_patch.stop)
        (self.docs / "job_requirements.md").write_text("Available in January.", encoding="utf-8")

    def test_merged_profile_and_optional_resume(self):
        profile = (
            "# Candidate Profile\n\n"
            "## Personal Details\nExample City\n\n"
            "## Technical Details\nExample project"
        )
        (self.docs / "candidate_profile.md").write_text(profile, encoding="utf-8")

        for resume in ("", "Example resume"):
            with self.subTest(resume=resume):
                context = application_questions._applicant_context(resume)
                self.assertIn(profile, context)
                self.assertIn("Available in January.", context)
                self.assertIn(resume or "(not provided)", context)

    def test_legacy_split_profile(self):
        profile = "# Candidate Profile\nExample degree"
        (self.docs / "candidate_profile.md").write_text(profile, encoding="utf-8")
        (self.docs / "personal_details.md").write_text("Example City", encoding="utf-8")
        (self.docs / "technical_details.md").write_text("Example project", encoding="utf-8")

        context = application_questions._applicant_context("")
        for fact in ("Example degree", "Example City", "Example project", "Available in January."):
            self.assertIn(fact, context)

    def test_merged_section_supersedes_only_its_legacy_file(self):
        (self.docs / "personal_details.md").write_text("Original city", encoding="utf-8")
        (self.docs / "technical_details.md").write_text("Original project", encoding="utf-8")
        for heading, superseded, retained in (
            ("Personal details", "Original city", "Original project"),
            ("Technical details", "Original project", "Original city"),
        ):
            with self.subTest(heading=heading):
                profile = f"# Candidate Profile\n\n## {heading}\nUpdated detail"
                (self.docs / "candidate_profile.md").write_text(profile, encoding="utf-8")
                context = application_questions._applicant_context("")
                self.assertIn("Updated detail", context)
                self.assertNotIn(superseded, context)
                self.assertIn(retained, context)
