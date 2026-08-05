"""Locate KeibaAI analysis/result CSV files by race_id.

This module only discovers file paths and pairs files that already exist.  It
does not read CSV contents, mutate files, run evaluators, or change legacy
folder handling.
"""

import re
from pathlib import Path

from evaluation.course_name_normalizer import FORMAL_COURSE_NAMES, normalize_course_name


class RaceFileLocator:
    """Find analysis and result CSV pairs for the new race_id file layout."""

    COURSE_NAMES = FORMAL_COURSE_NAMES

    ANALYSIS_PATTERNS = {
        "entry": re.compile(
            r"^race_(?P<date>\d{8})_(?P<course>[a-z]+)_(?P<race>\d{1,2}[rR])_entry\.csv$"
        ),
        "horses": re.compile(
            r"^race_(?P<date>\d{8})_(?P<course>[a-z]+)_(?P<race>\d{1,2}[rR])_horses\.csv$"
        ),
    }

    RESULT_PATTERNS = {
        "race_result": re.compile(
            r"^race_(?P<date>\d{8})_(?P<course>[a-z]+)_(?P<race>\d{1,2}[rR])_result\.csv$"
        ),
        "horse_result": re.compile(
            r"^horse_(?P<date>\d{8})_(?P<course>[a-z]+)_(?P<race>\d{1,2}[rR])_result\.csv$"
        ),
    }

    def find_analysis_pairs(self, base_dir="data/analysis"):
        """Return complete entry/horses pairs plus diagnostics."""

        found = self._find_files(base_dir, self.ANALYSIS_PATTERNS)
        return self._build_analysis_result(found)

    def find_result_pairs(self, base_dir="data/results"):
        """Return complete race_result/horse_result pairs plus diagnostics."""

        found = self._find_files(base_dir, self.RESULT_PATTERNS)
        return self._build_result_result(found)

    def find_complete_race_sets(
        self,
        analysis_dir="data/analysis",
        results_dir="data/results",
    ):
        """Return race sets where analysis and result pairs are both complete."""

        analysis = self.find_analysis_pairs(analysis_dir)
        results = self.find_result_pairs(results_dir)
        analysis_pairs = {item["race_id"]: item for item in analysis["pairs"]}
        result_pairs = {item["race_id"]: item for item in results["pairs"]}
        common_ids = sorted(set(analysis_pairs) & set(result_pairs))

        complete_sets = []
        for race_id in common_ids:
            row = {"race_id": race_id}
            row.update(analysis_pairs[race_id])
            row.update(result_pairs[race_id])
            complete_sets.append(row)

        return {
            "complete_sets": complete_sets,
            "analysis_only": [
                analysis_pairs[race_id]
                for race_id in sorted(set(analysis_pairs) - set(result_pairs))
            ],
            "results_only": [
                result_pairs[race_id]
                for race_id in sorted(set(result_pairs) - set(analysis_pairs))
            ],
            "warnings": self._combine_warnings(analysis, results),
        }

    def extract_race_id(self, filename):
        """Extract race_id from a supported analysis/result filename."""

        parsed = self.parse_filename(filename)
        return parsed.get("race_id") if parsed else None

    def parse_filename(self, filename):
        """Parse a supported filename into normalized race metadata."""

        name = Path(str(filename)).name
        for kind, patterns in [
            ("analysis", self.ANALYSIS_PATTERNS),
            ("result", self.RESULT_PATTERNS),
        ]:
            for role, pattern in patterns.items():
                match = pattern.match(name)
                if not match:
                    continue
                date = match.group("date")
                original_course = match.group("course").lower()
                course = normalize_course_name(original_course)
                race_number = self._normalize_race_number(match.group("race"))
                if not self._valid_parts(date, course, race_number):
                    return None
                return {
                    "kind": kind,
                    "role": role,
                    "race_id": f"race_{date}_{course}_{race_number}",
                    "race_date": date,
                    "racecourse": course,
                    "original_racecourse": original_course,
                    "race_number": race_number,
                }
        return None

    def _find_files(self, base_dir, patterns):
        base_path = Path(base_dir)
        warnings = []
        files = {}
        invalid_files = []
        if not base_path.exists() or not base_path.is_dir():
            return {"files": files, "duplicates": [], "warnings": [], "invalid_files": []}

        for path in base_path.rglob("*.csv"):
            parsed = self.parse_filename(path.name)
            if not parsed or parsed.get("role") not in patterns:
                invalid_files.append(str(path))
                continue
            race_id = parsed["race_id"]
            role = parsed["role"]
            files.setdefault(race_id, {}).setdefault(role, []).append(str(path))

        duplicates = self._duplicates(files)
        for item in duplicates:
            warnings.append(f"Duplicate {item['role']} files for {item['race_id']}")

        return {
            "files": files,
            "duplicates": duplicates,
            "warnings": warnings,
            "invalid_files": invalid_files,
        }

    def _build_analysis_result(self, found):
        pairs = []
        incomplete = []
        duplicate_keys = self._duplicate_keys(found["duplicates"])
        for race_id, roles in sorted(found["files"].items()):
            entry_paths = roles.get("entry", [])
            horses_paths = roles.get("horses", [])
            if (race_id, "entry") in duplicate_keys or (race_id, "horses") in duplicate_keys:
                continue
            if len(entry_paths) == 1 and len(horses_paths) == 1:
                pairs.append(
                    {
                        "race_id": race_id,
                        "entry_path": entry_paths[0],
                        "horses_path": horses_paths[0],
                    }
                )
                continue
            if entry_paths and not horses_paths:
                incomplete.append(
                    {
                        "race_id": race_id,
                        "status": "missing_horses",
                        "entry_path": entry_paths[0],
                        "horses_path": None,
                    }
                )
            elif horses_paths and not entry_paths:
                incomplete.append(
                    {
                        "race_id": race_id,
                        "status": "missing_entry",
                        "entry_path": None,
                        "horses_path": horses_paths[0],
                    }
                )
        return {
            "pairs": pairs,
            "incomplete": incomplete,
            "duplicates": found["duplicates"],
            "warnings": self._warnings_with_invalid(found),
        }

    def _build_result_result(self, found):
        pairs = []
        incomplete = []
        duplicate_keys = self._duplicate_keys(found["duplicates"])
        for race_id, roles in sorted(found["files"].items()):
            race_paths = roles.get("race_result", [])
            horse_paths = roles.get("horse_result", [])
            if (
                (race_id, "race_result") in duplicate_keys
                or (race_id, "horse_result") in duplicate_keys
            ):
                continue
            if len(race_paths) == 1 and len(horse_paths) == 1:
                pairs.append(
                    {
                        "race_id": race_id,
                        "race_result_path": race_paths[0],
                        "horse_result_path": horse_paths[0],
                    }
                )
                continue
            if race_paths and not horse_paths:
                incomplete.append(
                    {
                        "race_id": race_id,
                        "status": "missing_horse_result",
                        "race_result_path": race_paths[0],
                        "horse_result_path": None,
                    }
                )
            elif horse_paths and not race_paths:
                incomplete.append(
                    {
                        "race_id": race_id,
                        "status": "missing_race_result",
                        "race_result_path": None,
                        "horse_result_path": horse_paths[0],
                    }
                )
        return {
            "pairs": pairs,
            "incomplete": incomplete,
            "duplicates": found["duplicates"],
            "warnings": self._warnings_with_invalid(found),
        }

    def _warnings_with_invalid(self, found):
        warnings = list(found.get("warnings", []))
        for path in found.get("invalid_files", []):
            warnings.append(f"Ignored unsupported CSV filename: {path}")
        return warnings

    def _duplicates(self, files):
        duplicates = []
        for race_id, roles in sorted(files.items()):
            for role, paths in sorted(roles.items()):
                if len(paths) > 1:
                    duplicates.append(
                        {
                            "race_id": race_id,
                            "role": role,
                            "paths": paths,
                        }
                    )
        return duplicates

    def _duplicate_keys(self, duplicates):
        return {
            (item.get("race_id"), item.get("role"))
            for item in duplicates
            if isinstance(item, dict)
        }

    def _combine_warnings(self, analysis, results):
        warnings = []
        warnings.extend(analysis.get("warnings", []))
        warnings.extend(results.get("warnings", []))
        return warnings

    def _normalize_race_number(self, value):
        text = str(value or "").strip()
        match = re.search(r"\d+", text)
        if not match:
            return None
        number = int(match.group(0))
        return f"{number}R"

    def _valid_parts(self, date, course, race_number):
        if not re.match(r"^\d{8}$", str(date or "")):
            return False
        if course not in self.COURSE_NAMES:
            return False
        number_match = re.match(r"^(\d{1,2})R$", str(race_number or ""))
        if not number_match:
            return False
        number = int(number_match.group(1))
        return 1 <= number <= 12


if __name__ == "__main__":
    locator = RaceFileLocator()
    print(locator.find_analysis_pairs())
    print(locator.find_result_pairs())
