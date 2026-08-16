import uuid
import json
from datetime import datetime, timedelta
from services.db_service import db_service

class WeeklyTestService:
    def check_and_generate(self, user_id):
        """
        Check if the user needs a weekly test generated for their active semester.
        Tests are generated on Sundays.
        """
        today = datetime.now()
        
        # 1. Tests are only available on Sundays
        if today.weekday() != 6: # Sunday is 6
            return
            
        # 2. Check if admin has released tests for this week
        current_year, current_week, _ = today.isocalendar()
        week_key = f"WEEKLY_TEST_RELEASE_{current_year}_W{current_week}"
        
        release_status = db_service.query("SELECT key_value FROM system_settings WHERE key_name = ?", (week_key,), one=True)
        if not release_status or release_status["key_value"] != "approved":
            # Admin hasn't approved or has dismissed this week's tests
            return
            
        # Determine the cutoff date (7 days ago) to avoid regenerating if already exists
        seven_days_ago = today - timedelta(days=7)
        cutoff_date = seven_days_ago.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # 3. Enforce the "must register before Friday" rule
        user = db_service.query("SELECT created_at FROM users WHERE id = ?", (user_id,), one=True)
        if user and dict(user).get("created_at"):
            user_created = datetime.fromisoformat(user["created_at"])
            # Get the Friday of the current week (Sunday is 6, Friday is 4. So 2 days ago if today is Sunday)
            friday_cutoff = (today - timedelta(days=today.weekday() - 4)).replace(hour=0, minute=0, second=0, microsecond=0)
            if user_created >= friday_cutoff:
                print(f"[DEBUG] User {user_id} registered on or after Friday, skipping test for this week.")
                return

        print(f"[DEBUG] check_and_generate for user_id: {user_id}")
        semesters = db_service.query("SELECT * FROM semesters WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
        if not semesters:
            print(f"[DEBUG] No semesters found for user {user_id}")
            return
            
        print(f"[DEBUG] Found {len(semesters)} semesters for user {user_id}")
        active_sem = semesters[0]
        
        # Check if a combined test already exists in the last 7 days
        existing_test = db_service.query(
            "SELECT id FROM weekly_tests WHERE user_id = ? AND subject_id = 'ALL' AND created_at >= ?",
            (user_id, cutoff_date.isoformat())
        )
        
        if not existing_test:
            # Delete old tests to only keep the latest one (cleanup)
            db_service.execute("DELETE FROM weekly_test_answers WHERE test_id IN (SELECT id FROM weekly_tests WHERE user_id = ?)", (user_id,))
            db_service.execute("DELETE FROM weekly_tests WHERE user_id = ?", (user_id,))
            
            # Generate a new test instantly from question bank
            self.generate_instant_test(user_id, active_sem["id"])
                
    def generate_instant_test(self, user_id, sem_id):
        try:
            # 1. Fetch all subjects for this semester
            subjects = db_service.query("SELECT id, name FROM subjects WHERE semester_id = ?", (sem_id,))
            subject_ids = [sub["id"] for sub in subjects]
            
            if not subject_ids:
                return

            num_subjects = len(subject_ids)
            base_count = 20 // num_subjects
            remainder = 20 % num_subjects
            
            questions = []
            
            for i, sub_id in enumerate(subject_ids):
                target_count = base_count + (1 if i < remainder else 0)
                
                # Fetch unseen questions for this specific subject
                query = """
                    SELECT * FROM question_bank 
                    WHERE subject_id = ? 
                    AND id NOT IN (SELECT question_id FROM user_attempted_questions WHERE user_id = ?)
                    ORDER BY RANDOM() 
                    LIMIT ?
                """
                sub_questions = db_service.query(query, (sub_id, user_id, target_count))
                
                # Fallback if not enough unseen questions for this subject
                if len(sub_questions) < target_count:
                    needed = target_count - len(sub_questions)
                    fallback_query = """
                        SELECT * FROM question_bank 
                        WHERE subject_id = ? 
                        ORDER BY RANDOM() 
                        LIMIT ?
                    """
                    fallback_questions = db_service.query(fallback_query, (sub_id, needed))
                    
                    existing_ids = {q["id"] for q in sub_questions}
                    for fq in fallback_questions:
                        if fq["id"] not in existing_ids:
                            sub_questions.append(fq)
                            existing_ids.add(fq["id"])
                
                questions.extend(sub_questions)
                
            # Shuffle the final combined list so the test isn't grouped by subject
            import random
            random.shuffle(questions)

            if not questions:
                # No questions exist in bank at all yet
                print("No questions found in question bank for these subjects.")
                return

            # 3. Save test
            test_id = str(uuid.uuid4())
            # Convert questions to JSON array
            test_data = []
            for q in questions:
                # Mark as attempted
                db_service.execute(
                    "INSERT OR IGNORE INTO user_attempted_questions (user_id, question_id) VALUES (?, ?)", 
                    (user_id, q["id"])
                )
                
                test_data.append({
                    "id": q["id"],
                    "question": q["question"],
                    "options": json.loads(q["options"]),
                    "correct_answer": q["correct_answer"],
                    "explanation": q["explanation"],
                    "difficulty": q["difficulty"]
                })
                
            db_service.execute(
                """INSERT INTO weekly_tests (id, user_id, subject_id, title, test_data, status, total_questions)
                   VALUES (?, ?, 'ALL', ?, ?, 'approved', ?)""",
                (test_id, user_id, "Weekly Assessment: Advanced Review", json.dumps(test_data), len(test_data))
            )
            
        except Exception as e:
            print(f"Error generating weekly test from bank: {e}")

weekly_test_service = WeeklyTestService()

