import json
import os
from collections import defaultdict

class SyllabusService:
    def __init__(self, data_dir=None):
        if data_dir is None:
            # Construct absolute path relative to this file's location
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.data_dir = os.path.join(base_dir, "data", "syllabus")
        else:
            self.data_dir = data_dir

    PRETTY_NAMES = {
        "intermediate": "Intermediate",
        "diploma": "Diploma",
        "btech": "B.Tech Engineering",
        "tg": "TG Intermediate Board",
        "ap": "AP Intermediate Board",
        "sbtet_tg": "TG SBTET Board",
        "jntuh": "JNTUH / Autonomous Colleges",
        "jntu_tg": "JNTU (Telangana)",
        "jntu_ap": "JNTU (Andhra Pradesh)",
        "ou": "Osmania University (OU)",
        "c24_1st_sem": "C24 Curriculum - I Semester",
        "c24_2nd_sem": "C24 Curriculum - II Semester",
        "c24_3rd_sem": "C24 Curriculum - III Semester",
        "c24_4th_sem": "C24 Curriculum - IV Semester",
        "c24_5th_sem": "C24 Curriculum - V Semester",
        "first_year": "First Year",
        "second_year": "Second Year",
        "1st_year": "1st Year",
        "2nd_year_1st_sem": "II Year - I Semester (2-1)",
        "2nd_year_2nd_sem": "II Year - II Semester (2-2)",
        "3rd_year_1st_sem": "III Year - I Semester (3-1)",
        "3rd_year_2nd_sem": "III Year - II Semester (3-2)",
        "4th_year_1st_sem": "IV Year - I Semester (4-1)",
        "4th_year_2nd_sem": "IV Year - II Semester (4-2)"
    }

    def _format(self, items):
        return [{"id": item, "name": self.PRETTY_NAMES.get(item, item.replace('_', ' ').title())} for item in items]

    def get_available_education_levels(self):
        """Returns list of education levels (e.g. ['intermediate', 'btech'])"""
        if not os.path.exists(self.data_dir):
            return []
        items = [d for d in os.listdir(self.data_dir) if os.path.isdir(os.path.join(self.data_dir, d))]
        return self._format(items)

    def get_available_boards(self, education_level):
        """Returns list of boards (e.g. ['tg', 'ap']) for an education level"""
        path = os.path.join(self.data_dir, education_level)
        if not os.path.exists(path):
            return []
        items = [d for d in os.listdir(path) if os.path.isdir(os.path.join(path, d))]
        return self._format(items)

    def get_available_years(self, education_level, board):
        """Returns list of JSON files (e.g. ['first_year', 'second_year'])"""
        path = os.path.join(self.data_dir, education_level, board)
        if not os.path.exists(path):
            return []
        files = [f for f in os.listdir(path) if f.endswith(".json")]
        items = [f.replace(".json", "") for f in files]
        return self._format(items)

    def get_syllabus_data(self, education_level, board, year):
        """Loads and returns the JSON syllabus data"""
        filepath = os.path.join(self.data_dir, education_level, board, f"{year}.json")
        if not os.path.exists(filepath):
            return None
        with open(filepath, "r", encoding="utf-8-sig") as f:
            return json.load(f)

    def get_available_groups(self, education_level, board, year):
        """Returns available groups/branches (e.g. ['MPC', 'BiPC'])"""
        data = self.get_syllabus_data(education_level, board, year)
        if not data or "groups" not in data:
            return []
        return list(data["groups"].keys())

    def get_subjects_for_group(self, education_level, board, year, group):
        """Returns subjects, chapters, and topics for a specific group"""
        data = self.get_syllabus_data(education_level, board, year)
        if not data or "groups" not in data or group not in data["groups"]:
            return []
        return data["groups"][group]

syllabus_service = SyllabusService()

