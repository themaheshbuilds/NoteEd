import os
import base64
import json
import re
import time
import requests

def _handle_auth_error(e):
    if hasattr(e, 'response') and e.response is not None:
        if e.response.status_code in (401, 403):
            try:
                # pyrefly: ignore [missing-import]
                from flask import session
                session['api_key_invalid'] = True
                session.modified = True
            except Exception:
                pass

class RateLimitExhaustedError(Exception):
    pass

class AIService:
    def __init__(self):
        self.model = "meta/llama-3.1-8b-instruct"
        self.vision_model = "meta/llama-3.2-90b-vision-instruct"
        # Keep track of which key to use for load balancing
        self._key_index = 0


    def get_prioritized_configs(self, task_type="live"):
        """
        Returns a strict priority list of API configurations (key, base_url, chat_model, vision_model, platform)
        Priority: Gemini -> Groq -> Cerebras -> OpenRouter
        Supports intelligent load balancing based on BACKGROUND_KEY_PERCENTAGE.
        """
        from flask import session
        from services.db_service import db_service
        import os
        
        all_keys = {
            "gemini": [],
            "groq": [],
            "cerebras": [],
            "openrouter": [],
            "nvidia": [],
            "openai": []
        }
        
        allowed_db_keys = ["GLOBAL_AI_API_KEYS", "NVIDIA_NIM_PAID_API_KEY", "NVIDIA_NIM_API_KEYS", "NVIDIA_NIM_API_KEY", "GEMINI_API_KEYS", "GROQ_API_KEYS", "CEREBRAS_API_KEYS", "OPENROUTER_API_KEYS", "OPENAI_API_KEY"]
        
        # Load keys from DB and Env
        combined = []
        bg_percentage = 50
        try:
            rows = db_service.query("SELECT key_name, key_value FROM system_settings")
            if rows:
                for row in rows:
                    if row["key_name"] == "BACKGROUND_KEY_PERCENTAGE" and row["key_value"]:
                        try:
                            bg_percentage = int(row["key_value"])
                        except ValueError:
                            pass
                    if row["key_name"] in allowed_db_keys and row["key_value"]:
                        val = row["key_value"].strip()
                        if val and "your_" not in val.lower() and "replace" not in val.lower():
                            combined.append(val)
        except Exception:
            pass
            
        for ev in allowed_db_keys:
            val = os.getenv(ev)
            if val:
                val = val.strip()
                if val and "your_" not in val.lower() and "replace" not in val.lower():
                    combined.append(val)
                    
        keys_str = ",".join(combined)
        keys = [k.strip() for k in keys_str.split(",") if k.strip()]
        
        for key in keys:
            if len(key) < 15: continue
            
            ai_platform = None
            if key.startswith("sk-or-"): ai_platform = "openrouter"
            elif key.startswith("nvapi-"): ai_platform = "nvidia"
            elif key.startswith("AIza") or key.startswith("AQ."): ai_platform = "gemini"
            elif key.startswith("gsk_"): ai_platform = "groq"
            elif key.startswith("sk-"): ai_platform = "openai"
            else: ai_platform = "cerebras" # Assume Cerebras for unformatted keys if no other match, or maybe check specifically. 
            
            # Since Cerebras keys don't have a known fixed prefix yet, we can't strongly infer it unless it came from CEREBRAS_API_KEYS. 
            # We'll just map it to the dictionary.
            
            if ai_platform:
                all_keys[ai_platform].append(key)
                
        # Manually fetch Cerebras keys to be safe
        try:
            cer_row = db_service.query("SELECT key_value FROM system_settings WHERE key_name = 'CEREBRAS_API_KEYS'", one=True)
            if cer_row and cer_row["key_value"]:
                cer_keys = [k.strip() for k in cer_row["key_value"].split(",") if len(k.strip()) > 15]
                all_keys["cerebras"].extend(cer_keys)
        except: pass
        
        if os.getenv("CEREBRAS_API_KEYS"):
            cer_keys = [k.strip() for k in os.getenv("CEREBRAS_API_KEYS").split(",") if len(k.strip()) > 15]
            all_keys["cerebras"].extend(cer_keys)
            
        # Deduplicate
        for k in all_keys:
            all_keys[k] = list(set(all_keys[k]))
            
        # Priority Order: Gemini -> Groq -> Cerebras -> OpenRouter -> Nvidia -> OpenAI
        priority_order = ["gemini", "groq", "cerebras", "openrouter", "nvidia", "openai"]
        
        all_ordered_keys = []
        for plat in priority_order:
            for key in all_keys[plat]:
                all_ordered_keys.append({"key": key, "platform": plat})
                
        total_keys = len(all_ordered_keys)
        if total_keys == 0:
            return []
            
        bg_count = max(1, int(total_keys * (bg_percentage / 100.0))) if bg_percentage > 0 else 0
        live_count = total_keys - bg_count
        
        # If there's only 1 key, both live and background have to share it to avoid breaking
        if total_keys == 1:
            bg_keys = all_ordered_keys
            live_keys = all_ordered_keys
        else:
            # Top tier keys for live, bottom tier for background
            live_keys = all_ordered_keys[:live_count] if live_count > 0 else []
            bg_keys = all_ordered_keys[live_count:] if bg_count > 0 else []
            
        selected_keys = bg_keys if task_type == "background" else live_keys
        
        configs = []
        for item in selected_keys:
            cfg = self._get_config_for_key(item["key"], item["platform"])
            if cfg:
                configs.append(cfg)
                
        return configs

    def _get_config_for_key(self, key, platform):
        if platform == "openai":
            return (key, "https://api.openai.com/v1", "gpt-4o-mini", "gpt-4o", platform)
        elif platform == "gemini":
            return (key, "https://generativelanguage.googleapis.com/v1beta", "gemini-2.5-flash", "gemini-2.5-pro", platform)
        elif platform == "groq":
            return (key, "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile", "llama-3.2-90b-vision-preview", platform)
        elif platform == "cerebras":
            return (key, "https://api.cerebras.ai/v1", "llama3.1-8b", "llama3.1-8b", platform)
        elif platform == "openrouter":
            return (key, "https://openrouter.ai/api/v1", "meta-llama/llama-3.3-70b-instruct:free", "meta-llama/llama-3.3-70b-instruct:free", platform)
        elif platform == "nvidia":
            return (key, "https://integrate.api.nvidia.com/v1", self.model, self.vision_model, platform)
        return None

    def _get_config(self):
        """Restored for backward compatibility with methods not yet refactored to use get_prioritized_configs."""
        configs = self.get_prioritized_configs(task_type="live")
        if configs:
            cfg = configs[0]
            # Returns: key, base_url, chat_model, vision_model
            return cfg[0], cfg[1], cfg[2], cfg[3]
        return None, None, None, None

    @property
    def api_config(self):
        """Maintained for backward compatibility. Returns the first available key."""
        configs = self.get_prioritized_configs()
        if configs:
            return configs[0][0], configs[0][4]
        return None, "nvidia"

    @property
    def api_key(self):
        """Maintains backward compatibility for simple truthiness checks"""
        key, _ = self.api_config
        return key

    def _get_custom_instructions(self):
        try:
            # pyrefly: ignore [missing-import]
            from flask import session
            if "user_id" in session:
                from services.db_service import db_service
                profile = db_service.query("SELECT custom_instructions FROM profiles WHERE id = ?", (session["user_id"],), one=True)
                if profile and "custom_instructions" in profile.keys() and profile["custom_instructions"]:
                    return profile["custom_instructions"]
        except Exception:
            pass
        return ""


    def process_vision_document(self, image_bytes):
        """
        Sends the enhanced page image to the NVIDIA NIM Vision model
        and requests a comprehensive structured JSON extraction.
        """
        key, base_url, chat_model, vision_model = self._get_config()
        if not key:
            return self._get_mock_vision_response()

        encoded_image = base64.b64encode(image_bytes).decode("utf-8")
        image_url = f"data:image/jpeg;base64,{encoded_image}"
        
        prompt = """
        You are a highly advanced AI document understanding engine. 
        Analyze the provided document page (which could contain printed text, handwritten notes, diagrams, tables, flowcharts, mathematical formulas, or code snippets).
        Extract everything accurately. Read handwritten text using surrounding context. If any parts are completely unreadable, mark them as "[Unreadable]" but do not invent content.
        
        Return a strict JSON response in the following format:
        {
          "title": "Document/Topic Title",
          "subject": "Core Subject",
          "unit": "Appropriate Unit or Section if mentioned (otherwise 'General')",
          "topics": ["list of key subtopics covered"],
          "summary": "Detailed summary of the page contents",
          "full_text": "Complete, verbatim transcription of all text, mathematical equations, and code snippets, structured logically.",
          "important_points": ["Key takeaway point 1", "Key takeaway point 2"],
          "questions": ["Possible study/exam question 1 based on this", "Possible study/exam question 2"],
          "keywords": ["keyword1", "keyword2", "keyword3"]
        }
        """

        payload = {
            "model": vision_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_url}}
                    ]
                }
            ],
            "temperature": 0.2,
            "top_p": 1,
            "max_tokens": 1024
        }

        for attempt in range(6):
            try:
                headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
                response = requests.post(f"{base_url}/chat/completions", headers=headers, json=payload, timeout=60)
                response.raise_for_status()
                result = response.json()
                content = result["choices"][0]["message"]["content"]
                parsed_json = self._extract_json(content)
                if parsed_json:
                    return parsed_json
                return json.loads(content)
            except requests.exceptions.HTTPError as e:
                import time
                if e.response and e.response.status_code in [429, 401, 403]:
                    new_key, new_base_url, new_chat_model, new_vision_model = self._get_config()
                    if new_key and new_key != key:
                        key, base_url, vision_model = new_key, new_base_url, new_vision_model
                        payload["model"] = vision_model
                        headers["Authorization"] = f"Bearer {key}"
                    time.sleep(1)
                    continue
                else:
                    break
            except Exception as e:
                print(f"Error in Vision: {e}")
                break
                
        return self._get_mock_vision_response()

    def _normalize_text(self, text):
        import re
        text = text.lower()
        text = re.sub(r'[^\w\s]', '', text)
        words = text.split()
        stopwords = {"what", "is", "a", "an", "the", "of", "and", "in", "to", "how", "why", "can", "you", "tell", "me", "about", "explain", "describe", "define", "give", "provide", "details"}
        return set([w for w in words if w not in stopwords])

    def _get_cached_response(self, query_text, topic_id=None):
        from services.db_service import db_service
        from datetime import datetime, timedelta
        
        cutoff_date = (datetime.now() - timedelta(days=7)).isoformat()
        
        if topic_id:
            rows = db_service.query(
                "SELECT id, query_text, normalized_query, ai_response FROM ai_query_cache WHERE (topic_id = ? OR topic_id IS NULL) AND created_at >= ? ORDER BY created_at DESC LIMIT 50",
                (topic_id, cutoff_date)
            )
        else:
            rows = db_service.query(
                "SELECT id, query_text, normalized_query, ai_response FROM ai_query_cache WHERE created_at >= ? ORDER BY created_at DESC LIMIT 50",
                (cutoff_date,)
            )
            
        if not rows:
            return None
            
        query_set = self._normalize_text(query_text)
        if not query_set:
            return None
            
        best_match = None
        best_score = 0.0
        
        for row in rows:
            cached_set = set(row["normalized_query"].split(",")) if row["normalized_query"] else set()
            if not cached_set:
                continue
                
            intersection = len(query_set.intersection(cached_set))
            union = len(query_set.union(cached_set))
            score = intersection / union if union > 0 else 0
            
            if score > best_score:
                best_score = score
                best_match = row["ai_response"]
                
        if best_score >= 0.85:
            print(f"[Semantic Cache] Hit! Score: {best_score:.2f}")
            return best_match
            
        return None
        
    def _set_cached_response(self, query_text, ai_response, topic_id=None):
        from services.db_service import db_service
        query_set = self._normalize_text(query_text)
        if not query_set:
            return
        normalized_str = ",".join(query_set)
        
        db_service.execute(
            "INSERT INTO ai_query_cache (query_text, normalized_query, ai_response, topic_id) VALUES (?, ?, ?, ?)",
            (query_text, normalized_str, ai_response, topic_id)
        )

    def generate_chat_response(self, user_prompt, context_text, chat_history=None, image_base64=None, topic_id=None):
        """
        Chat with a document using Meta Llama 3 / Qwen on NVIDIA NIM.
        chat_history is a list of dicts: [{"role": "user"/"assistant", "content": "..."}]
        """
        # Check cache first
        cached = self._get_cached_response(user_prompt, topic_id=topic_id)
        if cached:
            return cached
            
        key, base_url, chat_model, vision_model = self._get_config()
        if not key:
            return "NVIDIA NIM API Key not set. Here is a simulated response based on your document content."

        # Truncate context to prevent context window overflow on custom models
        context_text = context_text[:4000] if context_text else ""
        
        system_prompt = self.HELIX_SYSTEM_PROMPT + f"""

You are currently in CHAT MODE helping a student understand their study materials.
Use the following document context to answer the student's question.
If the answer is not in the context, use your general knowledge but keep it relevant to the topic.

CRITICAL: Output ONLY the final conversational answer. Do NOT output internal thinking, reasoning steps, or headers like "Examining...", "Evaluating...", etc.
Be extremely encouraging, clear, and structure your responses with markdown.

MATH CONSTRAINTS: When explaining math, use '$$...$$' for display equations and '$...$' for inline equations.

Document Context:
{context_text}
"""

        custom_instr = self._get_custom_instructions()
        if custom_instr:
            system_prompt += f"\n\nUSER'S CUSTOM INSTRUCTIONS FOR AI BEHAVIOR:\n{custom_instr}\n"

        messages = [{"role": "system", "content": system_prompt}]
        if chat_history:
            # Append last 10 messages for conversational memory
            for msg in chat_history[-10:]:
                messages.append({"role": msg["role"], "content": msg["content"]})
                
        if image_base64:
            messages.append({
                "role": "user", 
                "content": [
                    {"type": "text", "text": user_prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
                ]
            })
        else:
            messages.append({"role": "user", "content": user_prompt})

        model_to_use = vision_model if image_base64 else chat_model
        
        payload = {
            "model": model_to_use,
            "messages": messages,
            "temperature": 0.7,
            "top_p": 1,
            "max_tokens": 2048
        }

        for attempt in range(6):
            try:
                headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
                response = requests.post(f"{base_url}/chat/completions", headers=headers, json=payload, timeout=120)
                response.raise_for_status()
                result = response.json()
                content = result["choices"][0]["message"]["content"]
                # Strip <think>...</think> tags if present, even if unclosed
                content = re.sub(r'<think>.*?(?:</think>|$)', '', content, flags=re.DOTALL).strip()
                
                # Save to cache
                self._set_cached_response(user_prompt, content, topic_id=topic_id)
                
                return content
            except requests.exceptions.HTTPError as e:
                _handle_auth_error(e)
                status = e.response.status_code if e.response is not None else 'unknown'
                print(f"Error in Chat NIM API (HTTP {status}): {e}")
                
                if status in [429, 401, 403, 500, 502, 503]:
                    # Fetch next key for rotation
                    new_key, new_base_url, new_chat_model, new_vision_model = self._get_config()
                    if new_key and new_key != key:
                        key, base_url = new_key, new_base_url
                        model_to_use = new_vision_model if image_base64 else new_chat_model
                        payload["model"] = model_to_use
                        headers["Authorization"] = f"Bearer {key}"
                    time.sleep(1 + attempt)
                    continue
                else:
                    return f"Apologies, I encountered an error communicating with the AI model ({status}). Please try again."
            except requests.exceptions.Timeout:
                return "The AI request timed out. Please try again with a shorter question."
            except Exception as e:
                print(f"Error in Chat NIM API: {e}")
                return "Apologies, I encountered an error communicating with the AI model. Please try again."
                
        return "The AI service is currently unavailable or rate-limited. Please wait a moment and try again."

    def explain_topic(self, topic_name, level="beginner", language="English"):
        """
        Explains a topic (supports 'beginner', 'intermediate', examples, and Telugu + English).
        """
        key, base_url, chat_model, vision_model = self._get_config()
        if not key:
            return f"Simulated explanation for '{topic_name}' in {language} at a {level} level."
            
        cache_query = f"explain {topic_name} at {level} level in {language}"
        cached = self._get_cached_response(cache_query)
        if cached:
            return cached

        prompt = f"""
        Explain the topic '{topic_name}' at a '{level}' level.
        """
        if language == "Telugu + English":
            prompt += " Explain in a friendly, conversational mix of Telugu and English (Tanglish), translating complex concepts clearly.\n"
        else:
            prompt += f" Explain in clean {language}.\n"

        prompt += """
        Please structure your response strictly using Markdown. Include the following sections:
        
        ### 📌 TL;DR
        A concise, one-sentence summary of the concept.
        
        ### 💡 Real-World Analogy
        A relatable analogy explaining how this concept works in everyday life.
        
        ### 📖 Core Concept
        A clear, step-by-step breakdown using bullet points.
        
        ### 💻 Example / Application
        Provide a code snippet, mathematical formula, or practical use case to demonstrate the concept.
        
        ### 🧠 Test Yourself
        A quick question for the student to ponder, to check their understanding.
        """

        system_prompt = self.HELIX_SYSTEM_PROMPT + "\nYou excel at simplifying complex ideas using modern formatting and real-world analogies. EXTREMELY IMPORTANT: If the topic involves programming, put code in Markdown code blocks, NEVER in LaTeX."
        custom_instr = self._get_custom_instructions()
        if custom_instr:
            system_prompt += f"\n\nUSER'S CUSTOM INSTRUCTIONS FOR AI BEHAVIOR:\n{custom_instr}\n"

        payload = {
            "model": chat_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "top_p": 1,
            "max_tokens": 1024
        }

        import time
        max_retries = 3
        for attempt in range(max_retries):
            try:
                headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
                response = requests.post(f"{base_url}/chat/completions", headers=headers, json=payload, timeout=60)
                
                if response.status_code == 429 and attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff: 1s, 2s, 4s
                    continue
                    
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                
                cache_query = f"explain {topic_name} at {level} level in {language}"
                self._set_cached_response(cache_query, content)
                
                return content
            except Exception as e:
                if attempt == max_retries - 1:
                    if "429" in str(e) or (hasattr(response, "status_code") and response.status_code == 429):
                        return "### ⏳ AI is resting (Rate Limit Exceeded)\n\nYou have made too many requests in a short time. Please wait 1-2 minutes before trying again. \n\n*If you are using the free Gemini API tier, you are limited to 15 requests per minute.*"
                    return f"### ❌ Error\nAn error occurred while generating the explanation: `{e}`"

    def parse_syllabus(self, syllabus_text):
        """
        Converts pasted syllabus text into a structured JSON representation of Subjects, Units, and Topics.
        """
        key, base_url, chat_model, vision_model = self._get_config()
        if not key:
            return self._get_mock_syllabus_response()

        prompt = f"""
        You are an expert academic data extractor. Your job is to strictly parse the provided raw syllabus text into a specific JSON schema.
        
        RULES:
        1. Extract all valid Subjects, Chapters (or Units), and Topics accurately based on the text.
        2. Do NOT invent or hallucinate topics (e.g., do not generate "Topic 1", "Topic 2"). Extract exactly what is written in the text.
        3. If a chapter has no explicit topics, break the chapter description into logical topic chunks, or leave the topics array empty if no sub-topics exist.
        4. Preserve subject codes if they exist.
        
        Syllabus Text:
        {syllabus_text}
        
        Return a strict JSON format matching:
        {{
          "subjects": [
            {{
              "subject": "Subject Name",
              "code": "Optional Code",
              "chapters": [
                {{
                  "name": "Unit/Chapter Title",
                  "topics": ["Exact Topic string 1", "Exact Topic string 2"]
                }}
              ]
            }}
          ]
        }}
        """

        payload = {
            "model": chat_model,
            "messages": [
                {"role": "system", "content": "You are an academic syllabus parser that extracts clean structured academic programs."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,
            "top_p": 1,
            "max_tokens": 2048
        }

        try:
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            response = requests.post(f"{base_url}/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            parsed_json = self._extract_json(content)
            if parsed_json:
                return parsed_json
            else:
                # If _extract_json couldn't parse it even aggressively, try a naive fallback
                return json.loads(content)
        except Exception as e:
            print(f"Error parsing syllabus: {e}")
            return self._get_mock_syllabus_response()

    def _extract_json(self, text):
        """Robustly extract and repair JSON from LLM output, especially small models like Qwen 1.5 4B."""
        if not text:
            return {}
        # Strip <think>...</think> tags
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
        # Try to extract from ```json ... ``` blocks
        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if json_match:
            text = json_match.group(1).strip()
        else:
            # Try to find the first { ... } block
            brace_match = re.search(r'(\{.*\})', text, re.DOTALL)
            if brace_match:
                text = brace_match.group(1).strip()

        def _try_parse(s):
            """Attempt to parse JSON with multiple repair strategies."""
            # Strategy 1: Direct parse
            try:
                return json.loads(s, strict=False)
            except json.JSONDecodeError:
                pass

            # Strategy 2: Fix trailing commas
            cleaned = re.sub(r',\s*([}\]])', r'\1', s)
            try:
                return json.loads(cleaned, strict=False)
            except json.JSONDecodeError:
                pass

            # Strategy 3: Fix unterminated strings by closing them
            # Count open braces/brackets and close them
            repaired = cleaned
            # If string ends mid-string (unterminated), close it
            # Check if we have an odd number of unescaped quotes
            in_string = False
            last_char = ''
            for ch in repaired:
                if ch == '"' and last_char != '\\':
                    in_string = not in_string
                last_char = ch
            if in_string:
                repaired += '"'

            # Close any open structures
            open_braces = repaired.count('{') - repaired.count('}')
            open_brackets = repaired.count('[') - repaired.count(']')
            # Remove trailing comma before closing
            repaired = repaired.rstrip()
            if repaired.endswith(','):
                repaired = repaired[:-1]
            repaired += ']' * max(0, open_brackets)
            repaired += '}' * max(0, open_braces)

            try:
                return json.loads(repaired, strict=False)
            except json.JSONDecodeError:
                pass

            return None

        def _clean_latex(s):
            """Strip LaTeX notation from a string to make it plain text."""
            if not isinstance(s, str):
                return s
            # Remove $$...$$ blocks
            s = re.sub(r'\$\$.*?\$\$', lambda m: m.group(0).strip('$'), s, flags=re.DOTALL)
            # Remove $...$ inline math delimiters
            s = re.sub(r'\$([^$]+?)\$', r'\1', s)
            # Remove \( ... \) and \[ ... \]
            s = re.sub(r'\\\((.+?)\\\)', r'\1', s)
            s = re.sub(r'\\\[(.+?)\\\]', r'\1', s)
            # Remove common LaTeX commands but keep their content
            s = re.sub(r'\\textbf\{([^}]*)\}', r'\1', s)
            s = re.sub(r'\\textit\{([^}]*)\}', r'\1', s)
            s = re.sub(r'\\text\{([^}]*)\}', r'\1', s)
            s = re.sub(r'\\frac\{([^}]*)\}\{([^}]*)\}', r'(\1)/(\2)', s)
            s = re.sub(r'\\sqrt\{([^}]*)\}', r'sqrt(\1)', s)
            # Remove remaining backslash-commands
            s = re.sub(r'\\[a-zA-Z]+', '', s)
            return s.strip()

        def clean_strings(data):
            """Recursively clean parsed JSON data."""
            if isinstance(data, dict):
                cleaned = {}
                for k, v in data.items():
                    cv = clean_strings(v)
                    # If a value is a string that looks like JSON, try to parse it
                    if isinstance(cv, str) and cv.strip().startswith('{'):
                        try:
                            inner = json.loads(cv, strict=False)
                            cv = clean_strings(inner)
                        except (json.JSONDecodeError, ValueError):
                            pass
                    cleaned[k] = cv
                return cleaned
            elif isinstance(data, list):
                return [clean_strings(item) for item in data]
            elif isinstance(data, str):
                s = data.replace('\\n', '\n')
                return s
            return data

        # --- Phase 1: Sanitize LaTeX backslashes that break JSON ---
        # Protect common LaTeX macros that collide with valid JSON escapes
        sanitized = text
        sanitized = re.sub(r'(?<!\\)\\f(?=[a-zA-Z])', r'\\\\f', sanitized)
        sanitized = re.sub(r'(?<!\\)\\r(?=[a-zA-Z])', r'\\\\r', sanitized)
        sanitized = re.sub(r'(?<!\\)\\t(?=[a-zA-Z])', r'\\\\t', sanitized)
        sanitized = re.sub(r'(?<!\\)\\b(?=[a-zA-Z])', r'\\\\b', sanitized)
        sanitized = re.sub(r'(?<!\\)\\n(?=abla|u\b|eq|otin|rightarrow|exists)', r'\\\\n', sanitized)
        sanitized = re.sub(r'(?<!\\)\\(?![\\"/bfnrtu])', r'\\\\', sanitized)

        result = _try_parse(sanitized)
        if result:
            return clean_strings(result)

        # --- Phase 2: More aggressive repair ---
        # Strip ALL backslash sequences that aren't valid JSON escapes
        aggressive = re.sub(r'\\(?![\\"/bfnrtu])', '', text)
        aggressive = re.sub(r',\s*([}\]])', r'\1', aggressive)
        result = _try_parse(aggressive)
        if result:
            return clean_strings(result)

        # --- Phase 3: Extract individual known keys by regex ---
        # Last resort: try to extract known keys manually from the raw text
        extracted = {}
        # Try to get notes
        notes_match = re.search(r'"notes"\s*:\s*"((?:[^"\\]|\\.)*)"', text, re.DOTALL)
        if notes_match:
            extracted["notes"] = notes_match.group(1).replace('\\n', '\n').replace('\\"', '"')
        # Try to get summary
        summary_match = re.search(r'"summary"\s*:\s*"((?:[^"\\]|\\.)*)"', text, re.DOTALL)
        if summary_match:
            extracted["summary"] = summary_match.group(1).replace('\\n', '\n').replace('\\"', '"')
        # Try to get flashcards array
        fc_match = re.search(r'"flashcards"\s*:\s*(\[.*?\])', text, re.DOTALL)
        if fc_match:
            fc_result = _try_parse(fc_match.group(1))
            if fc_result:
                extracted["flashcards"] = fc_result
        # Try to get quizzes array
        quiz_match = re.search(r'"quizzes"\s*:\s*(\[.*?\])', text, re.DOTALL)
        if quiz_match:
            quiz_result = _try_parse(quiz_match.group(1))
            if quiz_result:
                extracted["quizzes"] = quiz_result
        # Try to get viva_questions array
        viva_match = re.search(r'"viva_questions"\s*:\s*(\[.*?\])', text, re.DOTALL)
        if viva_match:
            viva_result = _try_parse(viva_match.group(1))
            if viva_result:
                extracted["viva_questions"] = viva_result

        # Extra extraction for single mini-quiz keys if we're trying to extract a single quiz
        q_match = re.search(r'"question"\s*:\s*"((?:[^"\\]|\\.)*)"', text, re.DOTALL)
        if q_match:
            extracted["question"] = q_match.group(1).replace('\\n', '\n').replace('\\"', '"')
            
        opts_match = re.search(r'"options"\s*:\s*(\[.*?\])', text, re.DOTALL)
        if opts_match:
            opts_result = _try_parse(opts_match.group(1))
            if opts_result:
                extracted["options"] = opts_result
                
        idx_match = re.search(r'"correct_index"\s*:\s*(\d+)', text)
        if idx_match:
            extracted["correct_index"] = int(idx_match.group(1))
            
        exp_match = re.search(r'"explanation"\s*:\s*"((?:[^"\\]|\\.)*)"', text, re.DOTALL)
        if exp_match:
            extracted["explanation"] = exp_match.group(1).replace('\\n', '\n').replace('\\"', '"')

        if extracted:
            return clean_strings(extracted)

        print(f"Failed to parse AI JSON. Raw text: {text[:300]}...")
        return {}

    # ── Helix AI System Prompt ──
    HELIX_SYSTEM_PROMPT = """You are Helix AI, an advanced educational assistant designed to teach and explain any academic subject from primary school to postgraduate and professional level.

Core Objective: Maximize the learner's understanding while maintaining complete factual accuracy.
Prioritize: Accuracy > Understanding > Clarity > Completeness > Readability.

Rules:
- Never fabricate facts, formulas, or information.
- Automatically detect the education level, subject, and difficulty from the user's input.
- Adapt your teaching style automatically.
- Explain concepts from simple to advanced.
- Build understanding before introducing technical details.

Mathematics Strategy:
- **Comprehensive and Long**: Do not generate short summaries. Provide deep, comprehensive coverage of the topic.
- **Minimal Theory**: Keep introductory theory to a bare minimum.
- **Theorems & Proofs**: Heavily emphasize core theorems, their exact statements, and their step-by-step proofs.
- **Problem Solving Focus**: Provide a large number of solved numerical problems. Show every calculation step clearly. Never skip intermediate steps.
- **Notation**: Explain symbols, variables, and mathematical notation clearly.
- Mention common mistakes and misconceptions explicitly.

Programming Strategy:
- Explain the underlying concept first.
- Explain syntax, keywords, every line of code, and program flow.
- Perform dry runs when helpful.
- Include time and space complexity when applicable.

Other Subjects:
- Explain what the concept is, why it exists, how it works, where it is used.
- Use examples and analogies whenever they improve understanding.
- Expand difficult concepts instead of summarizing them."""

    def _generate_partial(self, prompt, max_tokens=4096, retries=5, key=None, base_url=None, chat_model=None, custom_instr="", task_type="live"):
        """Call the LLM API with strict priority fallback and robust JSON extraction."""
        import requests
        import time
        import json
        
        configs = self.get_prioritized_configs(task_type=task_type)
        if not configs:
            return {}
            
        system_prompt_base = self.HELIX_SYSTEM_PROMPT + """

CRITICAL JSON OUTPUT RULES:
1. Output ONLY valid JSON. No markdown wrappers, no extra text.
2. When writing math, use LaTeX: '$$...$$' for block equations, '$...$' for inline.
3. For programming code, use Markdown code blocks (```language), NEVER LaTeX.
4. Because you are outputting JSON, double-escape all LaTeX backslashes (e.g. \\\\frac instead of \\frac)."""
        
        if custom_instr:
            system_prompt_base += f"\\n\\nUSER'S CUSTOM INSTRUCTIONS FOR AI BEHAVIOR:\\n{custom_instr}\\n"
            
        messages = [
            {"role": "system", "content": system_prompt_base},
            {"role": "user", "content": prompt}
        ]

        last_error = None
        
        for attempt in range(retries):
            for cfg in configs:
                cfg_key, cfg_base_url, cfg_chat_model, cfg_vision_model, platform = cfg
                
                try:
                    if platform == "gemini":
                        # Native Gemini Format
                        gemini_contents = []
                        sys_msg_text = ""
                        for m in messages:
                            if m["role"] == "system":
                                sys_msg_text += m["content"] + "\n\n"
                            else:
                                gemini_contents.append({
                                    "role": "user" if m["role"] == "user" else "model",
                                    "parts": [{"text": m["content"]}]
                                })
                            
                        gemini_payload = {
                            "contents": gemini_contents,
                            "generationConfig": {
                                "temperature": 0.5,
                                "maxOutputTokens": max_tokens,
                                "responseMimeType": "application/json"
                            }
                        }
                        
                        if sys_msg_text:
                            gemini_payload["systemInstruction"] = {
                                "parts": [{"text": sys_msg_text.strip()}]
                            }
                            
                        url = f"https://generativelanguage.googleapis.com/v1beta/models/{cfg_chat_model}:generateContent?key={cfg_key}"
                        headers = {"Content-Type": "application/json"}
                        
                        response = requests.post(url, headers=headers, json=gemini_payload, timeout=90)
                        response.raise_for_status()
                        result_data = response.json()
                        content = result_data["candidates"][0]["content"]["parts"][0]["text"]
                        
                        result = self._extract_json(content)
                        if result:
                            return result
                        print(f"[{platform.upper()}] Empty JSON extraction.")
                    else:
                        payload = {
                            "model": cfg_chat_model,
                            "messages": messages,
                            "temperature": 0.5,
                            "top_p": 1,
                            "max_tokens": max_tokens,
                            "response_format": {"type": "json_object"}
                        }
                        
                        # Exclude response_format for groq/cerebras if they don't support it reliably, but they usually do
                        
                        headers = {"Authorization": f"Bearer {cfg_key}", "Content-Type": "application/json"}
                        
                        response = requests.post(f"{cfg_base_url}/chat/completions", headers=headers, json=payload, timeout=90)
                        response.raise_for_status()
                        
                        content = response.json()["choices"][0]["message"]["content"]
                        result = self._extract_json(content)
                        if result:
                            return result
                        print(f"[{platform.upper()}] Empty JSON extraction.")
                except requests.exceptions.HTTPError as e:
                    _handle_auth_error(e)
                    status = e.response.status_code if e.response is not None else 'unknown'
                    print(f"[{platform.upper()}] API HTTP Error {status}: {e}")
                    last_error = e
                except Exception as e:
                    print(f"[{platform.upper()}] API Request Error: {e}")
                    last_error = e
            
            # If we exhausted all configs in this attempt, wait and retry
            print(f"[AI Service] All fallbacks exhausted for attempt {attempt + 1}. Retrying in 2 seconds...")
            time.sleep(2)
            
        print("[AI Service] ALL retries and API Fallbacks exhausted! Rate limit or global auth failure.")
        raise RateLimitExhaustedError("All AI providers failed. " + str(last_error))

    def generate_study_materials(self, topic_name, subject_name="", key=None, base_url=None, chat_model=None, custom_instr=""):
        """
        Generates comprehensive notes, flashcards, MCQs, and Viva questions for a given topic IN PARALLEL.
        """
        # Fetch config and instructions in the main thread (with Flask request context) if not passed
        if not key:
            key, base_url, chat_model, _ = self._get_config()
            custom_instr = self._get_custom_instructions()
            
        if not key:
            return self._get_mock_materials_response(topic_name, subject_name)

        import concurrent.futures
        
        context_str = f" in the context of the subject '{subject_name}'" if subject_name else ""

        is_local_cpu = "127.0.0.1" in base_url or "localhost" in base_url

        if is_local_cpu:
            # Simplified prompts for small local models (Qwen 1.5 4B etc.)
            # NO LaTeX, NO complex formatting, SHORT outputs
            prompts = {
                "notes_summary": f"""Generate study notes for: '{topic_name}'{context_str}.
Cover: definition, key concepts, important points, examples, and a summary.
Write about 300 words of notes.
Write math in plain text like "x^2 + y^2" not LaTeX.
Also write a short 100-word revision summary.
Return JSON: {{"notes": "your notes here as a single string with markdown headings", "summary": "short summary here"}}""",
                "flashcards": f"""Generate 4 flashcards for: '{topic_name}'.
Each has a question and answer. Keep answers short (1-2 sentences).
No LaTeX or math symbols. Write math in plain text.
Return JSON: {{"flashcards": [{{"question": "...", "answer": "..."}}]}}""",
                "quizzes": f"""Generate 3 multiple choice questions for: '{topic_name}'.
Each has 4 options labeled A through D. No LaTeX or backslash commands.
Return JSON: {{"quizzes": [{{"question": "...", "options": ["A. ...", "B. ...", "C. ...", "D. ..."], "correct_index": 0, "explanation": "..."}}]}}""",
                "viva": f"""Generate 4 short-answer questions for: '{topic_name}'.
Keep answers to 1-2 sentences. No LaTeX or backslash commands.
Return JSON: {{"viva_questions": [{{"question": "...", "answer": "..."}}]}}"""
            }
        else:
            prompts = {
                "notes_summary": f"""
            Generate extremely detailed, comprehensive textbook-style academic study notes for the topic: '{topic_name}'{context_str}.
            
            CRITICAL: The notes MUST be a MINIMUM of 1500 words. Produce long-form, exhaustive content. Do NOT summarize briefly. Be thorough and cover:
            - Definition and introduction to the concept
            - Core principles with detailed explanations (not just bullet points)
            - Key terminology with definitions
            - Step-by-step processes or algorithms if applicable
            - Real-world examples and practical applications
            - Common misconceptions and pitfalls
            - Comparison with related concepts
            - Advantages and disadvantages
            - Important formulas, theorems, proofs, or rules
            - Exam-oriented tips and key points to remember
            - **Step-by-step solved practice problems** with mathematical signs, derivations, and solutions
            
            STRICT ACADEMIC RULE: Do NOT include any historical backgrounds, conversational filler, or unnecessary fluff. A student needs to study efficiently. Focus purely on technical and academic facts, concepts, and problem-solving.
            
            MATH/EQUATIONS CONSTRAINT: You MUST convert ALL mathematical content to valid MathJax (LaTeX).
            This includes: Arithmetic, Algebra, Calculus, Matrices, Logic, Graph Theory, etc.
            Rules:
            - Convert every mathematical expression, symbol, formula, derivation, proof, piecewise function, or equation into valid LaTeX.
            - Use '$$...$$' for display equations and '$...$' for inline math.
            - Convert fractions to \\frac, roots to \\sqrt.
            - Use proper LaTeX commands for integrals, sums, limits, vectors, matrices, Greek letters, and all mathematical symbols.
            - Preserve all explanations, headings, lists, tables, and formatting.
            - Ensure the final output renders without errors in MathJax v3.
            
            CRITICAL JSON RULE: Because you are outputting JSON, you MUST double-escape all LaTeX backslashes so the JSON is valid. For example, write \\\\frac instead of \\frac.
            
            LENGTH CONSTRAINT: Keep the notes concise and highly condensed. You MUST finish the entire response within 1500 words to prevent truncation. Do not ramble.
            
            Also generate a separate concise revision summary (200-300 words).
            
            Return a strict JSON object:
            {{"notes": "<long markdown notes with headers, sub-headers, bullet points, code blocks, LaTeX equations>", "summary": "<concise revision summary>"}}
            """,
                "flashcards": f"""
            Generate exactly 10 high-quality flashcard objects for the topic: '{topic_name}'.
            Each flashcard should test a different key concept. 
            MATH CONSTRAINT: If the topic contains math/logic, use standard LaTeX math notation ('$$...$$' or '$...$') in questions/answers.
            CRITICAL JSON RULE: You MUST double-escape all LaTeX backslashes (e.g. \\\\frac instead of \\frac) for valid JSON.
            Return strict JSON:
            {{"flashcards": [{{"question": "...", "answer": "..."}}]}}
            """,
                "quizzes": f"""
            Generate exactly 5 MCQ quiz questions for the topic: '{topic_name}'.
            Each question should test understanding, not just recall.
            MATH CONSTRAINT: If the topic contains math/logic, use standard LaTeX math notation for equations and show step-by-step derivations in the explanation.
            CRITICAL JSON RULE: You MUST double-escape all LaTeX backslashes (e.g. \\\\frac instead of \\frac) for valid JSON.
            Return strict JSON:
            {{"quizzes": [{{"question": "...", "options": ["A", "B", "C", "D"], "correct_index": 0, "explanation": "..."}}]}}
            """,
                "viva": f"""
            Generate exactly 10 short-answer viva/oral exam questions with answers for: '{topic_name}'.
            MATH CONSTRAINT: If the topic contains math/logic, use standard LaTeX math notation.
            CRITICAL JSON RULE: You MUST double-escape all LaTeX backslashes for valid JSON.
            Return strict JSON:
            {{"viva_questions": [{{"question": "...", "answer": "..."}}]}}
            """
            }

        results = {}
        # Use 1 worker for local CPU to prevent parallel request thrashing
        max_workers = 1 if is_local_cpu else 3
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_key = {}
            for pkey, prompt in prompts.items():
                if is_local_cpu:
                    # Low token limits for local CPU to generate fast
                    tokens = 1200 if pkey == "notes_summary" else 400
                else:
                    # Higher token limits for cloud APIs
                    tokens = 6144 if pkey == "notes_summary" else 2048
                    
                # STAGGER REQUESTS to prevent triggering burst rate limits on free providers like Groq
                import time
                time.sleep(1)
                
                future_to_key[executor.submit(self._generate_partial, prompt, tokens, 6, key, base_url, chat_model, custom_instr)] = pkey
            for future in concurrent.futures.as_completed(future_to_key):
                try:
                    data = future.result()
                    if data:
                        results.update(data)
                except Exception as e:
                    print(f"Parallel execution error: {e}")

        # If generation failed completely, return what we have (may be empty)
        # The task worker will detect empty notes and mark the task as failed
        if not results.get("notes") and not results.get("summary"):
            print(f"AI generation failed completely for topic: {topic_name}")
            return {
                "notes": "",
                "summary": "",
                "flashcards": results.get("flashcards", []),
                "quizzes": results.get("quizzes", []),
                "viva_questions": results.get("viva_questions", []),
                "_generation_failed": True
            }
            
        final_result = {
            "notes": results.get("notes", ""),
            "summary": results.get("summary", ""),
            "flashcards": results.get("flashcards", []),
            "quizzes": results.get("quizzes", []),
            "viva_questions": results.get("viva_questions", [])
        }
        return final_result

    def _get_mock_vision_response(self):
        return {
            "title": "Sample Study Notes",
            "subject": "Computer Science",
            "unit": "Unit 1: Introductions",
            "topics": ["Artificial Intelligence", "Machine Learning", "Deep Learning"],
            "summary": "This document outlines the foundational definitions of AI, ML, and DL, showing their hierarchical relationship.",
            "full_text": "Artificial Intelligence is the broad concept of machines being able to carry out tasks in a smart way. Machine Learning is an application of AI based around the idea that we should give machines access to data and let them learn for themselves. Deep Learning is a subset of ML inspired by the structure of the human brain (neural networks).",
            "important_points": [
                "AI is the parent field.",
                "ML relies on data learning.",
                "DL uses deep artificial neural networks."
            ],
            "questions": [
                "Explain the key difference between Machine Learning and Deep Learning.",
                "What is the inspiration behind Deep Learning models?"
            ],
            "keywords": ["AI", "Machine Learning", "Neural Networks", "Deep Learning"]
        }

    def _get_mock_syllabus_response(self):
        return {
            "subjects": [
                {
                    "name": "Database Management Systems",
                    "code": "CS-302",
                    "units": [
                        {
                            "name": "Introduction & ER Model",
                            "number": 1,
                            "topics": ["DBMS Architecture", "Entity Relationship Diagrams", "Relational Model Concepts"]
                        },
                        {
                            "name": "Structured Query Language (SQL)",
                            "number": 2,
                            "topics": ["DDL & DML Queries", "Joins and Subqueries", "Triggers and Views"]
                        }
                    ]
                }
            ]
        }

    def _get_mock_materials_response(self, topic_name=None, subject_name=""):
        if topic_name:
            topic_lower = topic_name.lower().strip()
            subject_lower = subject_name.lower().strip()
            combined_context = f"{topic_lower} {subject_lower}"
            
            # ── Detect domain ──
            is_math = any(k in combined_context for k in [
                "math", "calculus", "algebra", "differentiat", "integrat", "derivative",
                "equation", "formula", "theorem", "proof", "trigonometr", "logarithm",
                "limit", "matrix", "matrices", "polynomial", "quadratic", "linear",
                "probability", "statistics", "number theory", "discrete", "graph theory",
                "geometry", "vector", "differential", "series", "sequence", "function"
            ])
            is_physics = any(k in combined_context for k in [
                "physics", "mechanics", "thermodynamic", "electr", "magnet", "optic",
                "wave", "quantum", "relativity", "newton", "force", "motion", "energy",
                "momentum", "gravit", "circuit", "resistor", "capacitor"
            ])
            is_chemistry = any(k in combined_context for k in [
                "chemistry", "chemical", "reaction", "organic", "inorganic", "periodic",
                "bond", "molecule", "atom", "compound", "acid", "base", "oxidation",
                "reduction", "electrochemistry", "thermochemistry"
            ])
            is_biology = any(k in combined_context for k in [
                "biology", "cell", "dna", "rna", "genetics", "evolution", "ecology",
                "anatomy", "physiology", "microb", "botan", "zoolog"
            ])
            
            # ── Domain-specific content ──
            if is_math:
                # Differentiation-specific check
                if any(k in combined_context for k in ["differentiat", "derivative"]):
                    notes_text = f"""# {topic_name}

## 1. Introduction

**{topic_name}** are the fundamental rules used in calculus to find the derivative of a function. The derivative measures the rate at which a function's output changes with respect to its input.

## 2. Key Differentiation Rules

### 2.1 Constant Rule
If f(x) = c (a constant), then f'(x) = 0.

### 2.2 Power Rule
If f(x) = x^n, then f'(x) = n * x^(n-1).
- Example: f(x) = x^3, then f'(x) = 3x^2

### 2.3 Constant Multiple Rule
If f(x) = c * g(x), then f'(x) = c * g'(x).

### 2.4 Sum/Difference Rule
If f(x) = g(x) +/- h(x), then f'(x) = g'(x) +/- h'(x).

### 2.5 Product Rule
If f(x) = g(x) * h(x), then f'(x) = g'(x)*h(x) + g(x)*h'(x).

### 2.6 Quotient Rule
If f(x) = g(x)/h(x), then f'(x) = [g'(x)*h(x) - g(x)*h'(x)] / [h(x)]^2.

### 2.7 Chain Rule
If f(x) = g(h(x)), then f'(x) = g'(h(x)) * h'(x).

## 3. Common Derivatives Table

| Function f(x) | Derivative f'(x) |
|---|---|
| x^n | n * x^(n-1) |
| e^x | e^x |
| ln(x) | 1/x |
| sin(x) | cos(x) |
| cos(x) | -sin(x) |
| tan(x) | sec^2(x) |

## 4. Solved Examples

**Example 1:** Find the derivative of f(x) = 3x^4 - 5x^2 + 7x - 2
- f'(x) = 12x^3 - 10x + 7

**Example 2:** Find the derivative of f(x) = (2x + 1)^5
Using Chain Rule: f'(x) = 5(2x + 1)^4 * 2 = 10(2x + 1)^4

**Example 3:** Find the derivative of f(x) = x^2 * sin(x)
Using Product Rule: f'(x) = 2x * sin(x) + x^2 * cos(x)

## 5. Common Mistakes
1. Forgetting to apply the chain rule to composite functions
2. Confusing the product rule with simply multiplying derivatives
3. Sign errors in the quotient rule
4. Forgetting that the derivative of a constant is 0

## 6. Exam Tips
- Memorize the standard derivatives table
- Always identify if the function is a product, quotient, or composition before differentiating
- Practice chain rule problems extensively
- Show all intermediate steps in exam answers"""
                    summary_text = f"{topic_name} include: Constant Rule (d/dx[c]=0), Power Rule (d/dx[x^n]=nx^(n-1)), Sum/Difference Rule, Product Rule (fg' + gf'), Quotient Rule, and Chain Rule (d/dx[f(g(x))] = f'(g(x))*g'(x)). Standard derivatives to memorize: d/dx[e^x]=e^x, d/dx[sin(x)]=cos(x), d/dx[ln(x)]=1/x."
                elif any(k in combined_context for k in ["integrat"]):
                    notes_text = f"""# {topic_name}

## 1. Introduction
**{topic_name}** is the reverse process of differentiation. Integration finds the antiderivative or area under a curve.

## 2. Basic Integration Rules

### 2.1 Power Rule for Integration
Integral of x^n dx = x^(n+1)/(n+1) + C, where n != -1

### 2.2 Constant Multiple Rule
Integral of c*f(x) dx = c * Integral of f(x) dx

### 2.3 Sum/Difference Rule
Integral of [f(x) +/- g(x)] dx = Integral of f(x) dx +/- Integral of g(x) dx

## 3. Standard Integrals

| Function | Integral |
|---|---|
| x^n | x^(n+1)/(n+1) + C |
| 1/x | ln|x| + C |
| e^x | e^x + C |
| sin(x) | -cos(x) + C |
| cos(x) | sin(x) + C |
| sec^2(x) | tan(x) + C |

## 4. Techniques of Integration
- **Substitution Method** (u-substitution)
- **Integration by Parts**: Integral of u dv = uv - Integral of v du
- **Partial Fractions**: For rational functions
- **Trigonometric Substitution**: For expressions involving sqrt(a^2 - x^2) etc.

## 5. Definite vs Indefinite Integrals
- **Indefinite integral**: Has + C (constant of integration)
- **Definite integral**: Has upper and lower limits, gives a numerical value

## 6. Solved Examples
**Example 1:** Integral of (3x^2 + 2x - 5) dx = x^3 + x^2 - 5x + C
**Example 2:** Integral of sin(3x) dx = -cos(3x)/3 + C (using substitution)"""
                    summary_text = f"{topic_name} covers antiderivatives and area computation. Key rules: Power Rule (x^(n+1)/(n+1)), standard integrals of trigonometric/exponential functions, and techniques like substitution, integration by parts, and partial fractions."
                else:
                    notes_text = f"""# {topic_name}

## 1. Introduction
**{topic_name}** is a fundamental concept in mathematics. This topic provides essential tools for problem-solving in algebra, calculus, and applied mathematics.

## 2. Core Concepts
- Definition and formal notation
- Key properties and theorems
- Relationship with other mathematical concepts
- Standard formulas and identities

## 3. Important Formulas
The key formulas and identities related to {topic_name} should be memorized for exams and practical applications.

## 4. Solved Examples
Step-by-step worked examples demonstrating the application of {topic_name} concepts.

## 5. Common Mistakes
1. Algebraic sign errors
2. Incorrect formula application
3. Missing edge cases or special conditions
4. Not simplifying final answers

## 6. Practice Problems
Regular practice with increasing difficulty levels is essential for mastery of {topic_name}."""
                    summary_text = f"{topic_name} is a core mathematical concept covering definitions, formulas, theorems, and problem-solving techniques. Essential for exams and practical applications in science and engineering."

                # Math flashcards
                if any(k in combined_context for k in ["differentiat", "derivative"]):
                    flashcards = [
                        {"question": "What is the Power Rule of differentiation?", "answer": "If f(x) = x^n, then f'(x) = n * x^(n-1). For example, d/dx[x^5] = 5x^4."},
                        {"question": "State the Product Rule.", "answer": "If f(x) = g(x)*h(x), then f'(x) = g'(x)*h(x) + g(x)*h'(x)."},
                        {"question": "What is the Chain Rule?", "answer": "If f(x) = g(h(x)), then f'(x) = g'(h(x)) * h'(x). Used for composite functions."},
                        {"question": "What is the derivative of sin(x)?", "answer": "The derivative of sin(x) is cos(x)."},
                        {"question": "State the Quotient Rule.", "answer": "If f(x) = g(x)/h(x), then f'(x) = [g'(x)*h(x) - g(x)*h'(x)] / [h(x)]^2."},
                    ]
                    quizzes = [
                        {"question": "What is the derivative of f(x) = 3x^4?", "options": ["12x^3", "12x^4", "3x^3", "4x^3"], "correct_index": 0, "explanation": "Using the Power Rule: f'(x) = 3 * 4 * x^(4-1) = 12x^3."},
                        {"question": "What is d/dx[e^x]?", "options": ["e^x", "x*e^(x-1)", "e^(x-1)", "1/e^x"], "correct_index": 0, "explanation": "The derivative of e^x is always e^x. This is a fundamental result."},
                        {"question": "Which rule is used to differentiate f(x) = sin(x^2)?", "options": ["Chain Rule", "Product Rule", "Power Rule", "Quotient Rule"], "correct_index": 0, "explanation": "sin(x^2) is a composite function: outer=sin, inner=x^2. Chain rule gives: cos(x^2) * 2x."},
                        {"question": "What is d/dx[ln(x)]?", "options": ["1/x", "ln(x)/x", "x", "e^x"], "correct_index": 0, "explanation": "The derivative of the natural logarithm ln(x) is 1/x."},
                    ]
                    viva = [
                        {"question": "Define differentiation.", "answer": "Differentiation is the process of finding the derivative of a function, measuring its instantaneous rate of change."},
                        {"question": "State the Power Rule.", "answer": "If f(x) = x^n, then f'(x) = n*x^(n-1)."},
                        {"question": "When do you use the Chain Rule?", "answer": "The Chain Rule is used when differentiating composite functions, i.e., a function inside another function."},
                        {"question": "What is the derivative of a constant?", "answer": "The derivative of any constant is 0."},
                        {"question": "How does the Product Rule differ from simply multiplying derivatives?", "answer": "The Product Rule states d/dx[f*g] = f'g + fg', NOT f'*g'. You cannot just multiply the individual derivatives."},
                    ]
                else:
                    flashcards = [
                        {"question": f"What is {topic_name}?", "answer": f"{topic_name} is a mathematical concept involving specific formulas, rules, and problem-solving techniques used in academic and applied contexts."},
                        {"question": f"Why is {topic_name} important?", "answer": f"It provides foundational tools for solving complex problems in mathematics, engineering, and science."},
                        {"question": f"What are the key formulas in {topic_name}?", "answer": "The key formulas depend on the specific subtopic but generally involve algebraic identities, function properties, and transformation rules."},
                        {"question": f"Name a common mistake in {topic_name}.", "answer": "Common mistakes include sign errors, incorrect formula application, and not checking special cases or boundary conditions."},
                    ]
                    quizzes = [
                        {"question": f"Which field does {topic_name} belong to?", "options": ["Mathematics", "Literature", "Geography", "History"], "correct_index": 0, "explanation": f"{topic_name} is a mathematical concept."},
                        {"question": f"What is essential for mastering {topic_name}?", "options": ["Regular practice with problems", "Memorizing Wikipedia articles", "Watching movies", "Physical exercise"], "correct_index": 0, "explanation": "Mathematical topics require consistent practice."},
                    ]
                    viva = [
                        {"question": f"Define {topic_name} in your own words.", "answer": f"{topic_name} involves mathematical principles, formulas, and techniques for solving specific types of problems."},
                        {"question": f"Give one practical application of {topic_name}.", "answer": f"{topic_name} is applied in engineering, physics, data science, and many real-world problem-solving scenarios."},
                    ]

            elif is_physics:
                notes_text = f"""# {topic_name}

## 1. Introduction
**{topic_name}** is a fundamental topic in Physics that describes how physical systems behave under specific conditions.

## 2. Core Principles
- Key laws and principles governing {topic_name}
- Mathematical formulations and equations
- Units of measurement and dimensional analysis

## 3. Important Formulas
The key equations and relationships for {topic_name} form the basis of problem-solving.

## 4. Applications
{topic_name} has applications in engineering, technology, and everyday life.

## 5. Solved Problems
Step-by-step solutions demonstrating the application of {topic_name} principles."""
                summary_text = f"{topic_name} is a Physics concept covering fundamental laws, equations, and practical applications. Key focus areas include mathematical formulations and real-world problem-solving."
                flashcards = [
                    {"question": f"What is {topic_name}?", "answer": f"{topic_name} describes physical phenomena governed by specific laws and mathematical equations."},
                    {"question": f"Name a key formula in {topic_name}.", "answer": f"The core formulas depend on the specific aspect of {topic_name} being studied."},
                ]
                quizzes = [{"question": f"Which branch of science does {topic_name} belong to?", "options": ["Physics", "Chemistry", "Biology", "Computer Science"], "correct_index": 0, "explanation": f"{topic_name} is a Physics topic."}]
                viva = [{"question": f"Explain the significance of {topic_name}.", "answer": f"{topic_name} helps us understand natural phenomena and build engineering solutions."}]

            elif is_chemistry:
                notes_text = f"""# {topic_name}

## 1. Introduction
**{topic_name}** is a core Chemistry concept covering the behavior of matter at the atomic and molecular level.

## 2. Key Concepts
- Atomic/molecular structure
- Reactions and mechanisms
- Thermodynamic and kinetic aspects
- Practical applications

## 3. Important Reactions and Equations
The balanced equations and reaction mechanisms related to {topic_name}.

## 4. Applications
Industrial, pharmaceutical, and environmental applications of {topic_name}."""
                summary_text = f"{topic_name} is a Chemistry concept covering reactions, molecular behavior, and practical applications in industry and research."
                flashcards = [
                    {"question": f"What is {topic_name}?", "answer": f"{topic_name} involves chemical principles, reactions, and molecular-level understanding of matter."},
                ]
                quizzes = [{"question": f"Which subject does {topic_name} belong to?", "options": ["Chemistry", "Mathematics", "History", "Geography"], "correct_index": 0, "explanation": f"{topic_name} is a Chemistry concept."}]
                viva = [{"question": f"Explain {topic_name} briefly.", "answer": f"{topic_name} covers chemical principles and their applications."}]

            else:
                # Generic academic fallback (not CS-specific)
                notes_text = f"""# {topic_name}

## 1. Introduction and Definition
**{topic_name}** is an important academic concept. Understanding this topic thoroughly is essential for exams and practical applications.

## 2. Core Concepts and Principles
- Key definitions and terminology
- Fundamental principles and rules
- Important relationships and connections

## 3. Detailed Explanation
{topic_name} involves understanding several interconnected ideas:
1. **Foundation** — The basic building blocks of the concept
2. **Application** — How the concept is applied in practice
3. **Analysis** — Breaking down complex scenarios
4. **Evaluation** — Assessing results and drawing conclusions

## 4. Practical Examples
Understanding {topic_name} requires working through real examples and practice problems.

## 5. Common Mistakes
1. Misunderstanding key definitions
2. Incorrect application of rules
3. Not considering edge cases
4. Rushing through problems without checking work

## 6. Exam Tips
- Understand the 'why' behind each concept, not just the 'what'
- Practice with past exam papers
- Create summary sheets for quick revision
- Focus on commonly tested subtopics"""
                summary_text = f"{topic_name} covers key definitions, principles, practical applications, and problem-solving techniques. Regular practice and understanding of core concepts is essential for mastery."
                flashcards = [
                    {"question": f"What is {topic_name}?", "answer": f"{topic_name} is an academic concept involving specific principles, rules, and practical applications within its field."},
                    {"question": f"Why is {topic_name} important?", "answer": f"Understanding {topic_name} is essential for exams and provides the foundation for advanced topics in the field."},
                    {"question": f"What are common mistakes in {topic_name}?", "answer": "Common mistakes include misunderstanding definitions, incorrect rule application, and not considering special cases."},
                ]
                quizzes = [
                    {"question": f"Which approach is best for studying {topic_name}?", "options": ["Understanding concepts and practicing problems", "Only reading notes once", "Skipping difficult sections", "Memorizing without understanding"], "correct_index": 0, "explanation": "Active learning through practice and understanding is the most effective approach."},
                ]
                viva = [
                    {"question": f"Define {topic_name} in your own words.", "answer": f"{topic_name} involves understanding specific principles and their applications within the broader subject area."},
                    {"question": f"Give a practical application of {topic_name}.", "answer": f"{topic_name} can be applied in real-world scenarios related to its field of study."},
                ]

            return {
                "notes": notes_text,
                "summary": summary_text,
                "flashcards": flashcards,
                "quizzes": quizzes,
                "viva_questions": viva,
            }

    def process_natural_language_command(self, user_command):
        """
        AI Planner is deprecated in favor of Centralized JSON Syllabus Setup.
        """
        return {"error": "AI Planner is deprecated. Please use the Setup Wizard to load your syllabus."}

    def generate_topic_materials_for_name(self, topic_name, subject_name="", key=None, base_url=None, chat_model=None, custom_instr=""):
        """
        Generate enriched, topic-specific study materials.
        Uses NVIDIA NIM when available; otherwise returns curated mock data
        for known topics or delegates to the generic mock fallback.
        """
        actual_key = key or self.api_key
        if actual_key:
            return self.generate_study_materials(topic_name, subject_name, key=actual_key, base_url=base_url, chat_model=chat_model, custom_instr=custom_instr)

        # Fallback: generate a reasonable mock for unknown topics
        return {
            "notes": f"# {topic_name}\n\n## Overview\n{topic_name} is a fundamental concept in computer science that every student should master.\n\n## Key Concepts\n- Core principles and definitions\n- Practical applications and use cases\n- Common implementation patterns\n- Performance considerations\n\n## Summary\nUnderstanding {topic_name} is essential for building a strong foundation in this subject area.",
            "summary": f"{topic_name} covers fundamental principles, practical applications, and implementation strategies that are essential for academic and professional success.",
            "flashcards": [
                {"question": f"What is {topic_name}?", "answer": f"{topic_name} is a key concept that involves understanding core principles and their practical applications in the field."},
                {"question": f"Why is {topic_name} important?", "answer": f"{topic_name} provides foundational knowledge required for advanced topics and real-world problem solving."},
            ],
            "quizzes": [
                {
                    "question": f"Which of the following best describes {topic_name}?",
                    "options": [
                        f"A fundamental concept in the subject",
                        "An unrelated mathematical theorem",
                        "A hardware component",
                        "A programming language",
                    ],
                    "correct_index": 0,
                    "explanation": f"{topic_name} is a core concept within its subject domain.",
                }
            ],
            "viva_questions": [
                {"question": f"Explain the significance of {topic_name}.", "answer": f"{topic_name} is significant because it forms the basis for understanding more advanced concepts and has wide practical applications."},
            ],
        }

    def triage_support_request(self, user_message):
        """Triages user support requests, classifies if admin intervention is needed, and provides an initial answer."""
        system_prompt = """
        You are the official Customer Support AI for Helix AI. 
        Your primary role is to assist users with billing, platform issues, and account management. 
        
        CRITICAL RULES:
        1. YOU MUST STRICTLY REFUSE TO ANSWER ANY STUDY-RELATED QUESTIONS, HOMEWORK, OR ACADEMIC TOPICS.
           If a user asks a study question, reply: "I am the Support AI and can only help with account, billing, and platform issues. For study help, please use your Dashboard study tools."
        2. TERMS & CONDITIONS: Users are responsible for their API keys if they use the free tier. 
        3. REFUND POLICY: Refunds are only provided if there is a double charge or platform error. Issues caused by the user's API key or third-party service downtime are NON-REFUNDABLE.
        4. If the user's issue involves a refund request, a bug report, a missing premium upgrade, or account deletion, set `needs_admin` to true.
        5. For simple questions about how the platform works, answer them nicely and set `needs_admin` to false.
        
        Output MUST be valid JSON only (no markdown wrapping) in this format:
        {
            "answer": "Your detailed response to the user here.",
            "needs_admin": true/false
        }
        """
        
        try:
            parsed = self._generate_partial(prompt=user_message, custom_instr=system_prompt)
        except RateLimitExhaustedError:
            return {"answer": "Our AI support is temporarily offline due to high traffic. We have forwarded your request to the admin team.", "needs_admin": True}
        
        if not parsed:
            return {"answer": "An error occurred while processing your request. It has been forwarded to our admin team.", "needs_admin": True}
            
        return {
            "answer": parsed.get("answer", "Thank you for your message. An admin will review it."),
            "needs_admin": parsed.get("needs_admin", True)
        }

ai_service = AIService()
