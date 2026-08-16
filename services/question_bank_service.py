import uuid
import json
import random
import concurrent.futures
from services.db_service import db_service
from services.ai_service import ai_service

class QuestionBankService:
    def __init__(self):
        self.TARGET_QUESTIONS_PER_TOPIC = 20  # Keep it small initially for testing
        
    def replenish_bank(self):
        """
        Background job to check all topics and replenish the question bank if needed.
        Runs in a separate thread so it doesn't block the main app.
        """
        import time
        print("[QuestionBank] Starting replenishment check...")
        try:
            topics = db_service.query("""
                SELECT t.id as topic_id, t.name as topic_name, u.id as unit_id, s.id as subject_id, s.name as subject_name
                FROM topics t
                JOIN units u ON t.unit_id = u.id
                JOIN subjects s ON u.subject_id = s.id
            """)
            
            topics_replenished = 0
            for topic in topics:
                if topics_replenished >= 5:
                    print("[QuestionBank] Reached max 5 topics for this run. Pausing until next cron job to respect API rate limits.")
                    break
                    
                # Count current questions for this topic
                count_res = db_service.query(
                    "SELECT COUNT(*) as count FROM question_bank WHERE topic_id = ?", 
                    (topic["topic_id"],), 
                    one=True
                )
                current_count = count_res["count"] if count_res else 0
                
                if current_count < self.TARGET_QUESTIONS_PER_TOPIC:
                    needed = self.TARGET_QUESTIONS_PER_TOPIC - current_count
                    print(f"[QuestionBank] Topic {topic['topic_name']} needs {needed} questions. Generating...")
                    try:
                        self._generate_and_insert_questions(topic, min(needed, 10)) # Max 10 per request to avoid rate limits
                        topics_replenished += 1
                        time.sleep(5)  # Pause to avoid 429 Too Many Requests
                    except Exception as e:
                        from services.ai_service import RateLimitExhaustedError
                        if isinstance(e, RateLimitExhaustedError):
                            print(f"[QuestionBank] Rate Limit Exhausted across all allocated Background providers! Queueing for 60 minutes...")
                            time.sleep(3600)
                        else:
                            print(f"[QuestionBank] Error generating questions for {topic['topic_name']}: {e}")
                    
        except Exception as e:
            print(f"[QuestionBank] Error during replenishment: {e}")
            
    def _generate_and_insert_questions(self, topic, count):
        prompt = f"""
        You are an expert exam creator.
        Generate EXACTLY {count} Multiple Choice Questions (MCQs) for the topic '{topic['topic_name']}' in the subject '{topic['subject_name']}'.
        Mix the difficulty levels (Beginner, Intermediate, Topper).
        
        Output MUST be valid JSON strictly matching this schema:
        {{
            "questions": [
                {{
                    "difficulty": "Intermediate",
                    "question": "What is the primary function of...?",
                    "options": ["A", "B", "C", "D"],
                    "correct_answer": "B",
                    "explanation": "Because..."
                }}
            ]
        }}
        """
        
        try:
            response = ai_service._generate_partial(prompt, task_type="background")
            if response and isinstance(response, dict) and "questions" in response:
                questions = response.get("questions", [])
                for q in questions:
                    qid = str(uuid.uuid4())
                    db_service.execute(
                        """INSERT INTO question_bank 
                           (id, subject_id, unit_id, topic_id, difficulty, question, options, correct_answer, explanation)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (qid, topic["subject_id"], topic["unit_id"], topic["topic_id"], 
                         q.get("difficulty", "Beginner"), q.get("question"), 
                         json.dumps(q.get("options", [])), q.get("correct_answer"), q.get("explanation", ""))
                    )
                print(f"[QuestionBank] Inserted {len(questions)} questions for {topic['topic_name']}.")
        except Exception as e:
            from services.ai_service import RateLimitExhaustedError
            if isinstance(e, RateLimitExhaustedError):
                raise e
            print(f"[QuestionBank] Error parsing questions for {topic['topic_name']}: {e}")

question_bank_service = QuestionBankService()

