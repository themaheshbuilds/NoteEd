import threading
import uuid
import traceback
from datetime import datetime
from services.db_service import db_service
from services.ai_service import ai_service

class TaskService:
    def __init__(self):
        pass
        
    def start_generate_materials_task(self, user_id, topics_to_generate, run_sync=False, archive_old=False, delete_chats=False, gen_options=None):
        """
        Spawns a background thread (or runs synchronously) to generate materials for a list of topics.
        Returns the task_id.
        """
        task_id = str(uuid.uuid4())
        # 4 generation sub-items per topic: Notes & Summary, Flashcards, MCQ Quiz, Viva Qs
        total_items = max(1, len(topics_to_generate) * 4)
        
        # Insert initial task record
        db_service.execute(
            """INSERT INTO background_tasks (id, user_id, task_type, status, total_items, completed_items, message)
               VALUES (?, ?, 'generate_study_materials', 'pending', ?, 0, 'Task queued')""",
            (task_id, user_id, total_items)
        )
        
        if run_sync:
            self._generate_materials_worker(task_id, topics_to_generate, archive_old, delete_chats, gen_options=gen_options)
        else:
            # Start thread
            thread = threading.Thread(
                target=self._generate_materials_worker,
                args=(task_id, topics_to_generate, archive_old, delete_chats, gen_options)
            )
            thread.daemon = True
            thread.start()
            
        return task_id
        
    def _generate_materials_worker(self, task_id, topics_to_generate, archive_old=False, delete_chats=False, gen_options=None):
        try:
            # Update status to processing
            db_service.execute(
                "UPDATE background_tasks SET status = 'processing', message = 'Analyzing topic & subject context...', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (task_id,)
            )

            # Fetch user_id from task
            task = db_service.query("SELECT user_id FROM background_tasks WHERE id = ?", (task_id,), one=True)
            user_id = task["user_id"] if task else None

            # ── All AI traffic goes through OmniRoute ────────────────────────
            key, base_url, chat_model, _ = ai_service._get_omni_config()
            custom_instr = ""
            study_purpose = "learning"
            is_premium = False

            if user_id:
                profile = db_service.query(
                    "SELECT custom_instructions, math_learning_level, experience_level, "
                    "is_premium, study_purpose FROM profiles WHERE id = ?",
                    (user_id,), one=True
                )
                if profile:
                    profile = dict(profile)
                    custom_instr  = profile.get("custom_instructions") or ""
                    study_purpose = profile.get("study_purpose") or "learning"
                    is_premium    = bool(profile.get("is_premium"))
            # ─────────────────────────────────────────────────────────────────

            completed = 0

            for topic_idx, topic_data in enumerate(topics_to_generate):
                if isinstance(topic_data, (tuple, list)):
                    tid = topic_data[0]
                    tname = topic_data[1]
                    sname = topic_data[2] if len(topic_data) > 2 else ""
                    exp_level = topic_data[3] if len(topic_data) > 3 else "intermediate"
                else:
                    topic_dict = dict(topic_data) if not isinstance(topic_data, dict) else topic_data
                    tid = topic_dict.get("id")
                    tname = topic_dict.get("name")
                    sname = topic_dict.get("subject_name", "")
                    exp_level = topic_dict.get("experience_level", "intermediate")
                
                # Check if task was cancelled by user
                task_status = db_service.query("SELECT status FROM background_tasks WHERE id = ?", (task_id,), one=True)
                if task_status and task_status["status"] == "cancelled":
                    print(f"Task {task_id} cancelled by user, aborting worker.")
                    return
                
                db_service.execute(
                    "UPDATE background_tasks SET status = 'processing', completed_items = ?, message = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (topic_idx * 4, f"Generating Notes & Core Concepts for '{tname}' (0/4)...", task_id)
                )
                    
                try:
                    topic_custom_instr = custom_instr
                    
                    materials = ai_service.generate_topic_materials_for_name(
                        tname, 
                        subject_name=sname, 
                        key=key, 
                        base_url=base_url, 
                        chat_model=chat_model, 
                        custom_instr=topic_custom_instr,
                        task_id=task_id,
                        study_purpose=study_purpose,
                        base_completed=topic_idx * 4,
                        gen_options=gen_options
                    )
                    
                    # Check if generation failed
                    if materials.get("_generation_failed"):
                        db_service.execute(
                            "UPDATE background_tasks SET status = 'failed', message = 'AI generation failed for this topic. Please try again.', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                            (task_id,)
                        )
                        print(f"Generation failed for topic: {tname}")
                        completed += 1
                        continue
                    
                    # Archive old materials only after successful generation
                    if archive_old:
                        db_service.execute(
                            "UPDATE notes SET is_archived = 1 WHERE topic_id = ? AND is_archived = 0",
                            (tid,)
                        )
                        db_service.execute(
                            "UPDATE flashcards SET is_archived = 1 WHERE topic_id = ? AND is_archived = 0",
                            (tid,)
                        )
                        db_service.execute(
                            "UPDATE quizzes SET is_archived = 1 WHERE topic_id = ? AND is_archived = 0",
                            (tid,)
                        )
                        
                    if delete_chats:
                        db_service.execute("DELETE FROM chat_messages WHERE topic_id = ?", (tid,))
                        db_service.execute("DELETE FROM chat_sessions WHERE topic_id = ?", (tid,))
                    
                    # Save notes
                    if materials.get("notes"):
                        note_id = str(uuid.uuid4())
                        db_service.execute(
                            """INSERT INTO notes (id, topic_id, title, content, is_ai_generated, is_archived)
                               VALUES (?, ?, ?, ?, 1, 0)""",
                            (note_id, tid, f"AI Notes: {tname}", materials["notes"])
                        )

                    # Save flashcards
                    for card in materials.get("flashcards", []):
                        card_id = str(uuid.uuid4())
                        db_service.execute(
                            """INSERT INTO flashcards (id, topic_id, question, answer, difficulty, box_number, is_archived)
                               VALUES (?, ?, ?, ?, 'medium', 1, 0)""",
                            (card_id, tid, card["question"], card["answer"])
                        )

                    # Save Revision Summary
                    if materials.get("summary"):
                        summary_id = str(uuid.uuid4())
                        db_service.execute(
                            """INSERT INTO notes (id, topic_id, title, content, is_ai_generated, is_archived)
                               VALUES (?, ?, ?, ?, 1, 0)""",
                            (summary_id, tid, f"AI Revision Summary: {tname}", materials["summary"])
                        )

                    # Save quiz
                    quiz_data = materials.get("quizzes", materials.get("quiz", []))
                    if quiz_data:
                        import json
                        quiz_id = str(uuid.uuid4())
                        db_service.execute(
                            """INSERT INTO quizzes (id, topic_id, title, quiz_data, is_archived)
                               VALUES (?, ?, ?, ?, 0)""",
                            (quiz_id, tid, f"AI MCQ Quiz: {tname}", json.dumps(quiz_data))
                        )

                    # Save Viva Voce / Oral Technical Questions
                    viva_data = materials.get("viva_questions", materials.get("viva", []))
                    if viva_data:
                        viva_md = "## 🎙️ Viva Voce & Technical Oral Exam Q&A\n\n"
                        viva_md += "Master these high-yield oral exam and technical interview questions to test your depth of understanding:\n\n"
                        for idx, v in enumerate(viva_data, 1):
                            q_text = v.get("question", "")
                            a_text = v.get("answer", "")
                            viva_md += f"### Q{idx}. {q_text}\n\n"
                            viva_md += f"**Answer:** {a_text}\n\n---\n\n"

                        viva_id = str(uuid.uuid4())
                        db_service.execute(
                            """INSERT INTO notes (id, topic_id, title, content, is_ai_generated, is_archived)
                               VALUES (?, ?, ?, ?, 1, 0)""",
                            (viva_id, tid, f"🎙️ Viva Voce & Oral Q&A: {tname}", viva_md)
                        )
                except Exception as e:
                    print(f"Error generating material for topic {tname}: {e}")
                    # Continue with other topics
                
                completed = (topic_idx + 1) * 4
                db_service.execute(
                    "UPDATE background_tasks SET completed_items = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (completed, task_id)
                )
                
            # Finish task  
            final_status = db_service.query("SELECT status FROM background_tasks WHERE id = ?", (task_id,), one=True)
            if final_status and final_status["status"] != "failed":
                db_service.execute(
                    "UPDATE background_tasks SET status = 'completed', message = 'Generation complete!', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (task_id,)
                )
            
        except Exception as e:
            traceback.print_exc()
            db_service.execute(
                "UPDATE background_tasks SET status = 'failed', message = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (str(e), task_id)
            )

task_service = TaskService()

