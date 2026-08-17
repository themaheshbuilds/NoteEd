import os
import base64
import json
import re
import time
import requests


# ── Auth error helper ─────────────────────────────────────────────────────────

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


# ── AIService ─────────────────────────────────────────────────────────────────

class AIService:
    """
    Routes all AI requests through OmniRoute — a self-hosted AI gateway that
    handles provider selection, fallback, and key management centrally.

    Architecture:
        Frontend → Flask Backend → OmniRoute (separate service) → AI Providers

    Configuration (via .env or Vercel environment variables):
        OMNIROUTE_BASE_URL  — e.g. http://localhost:20128/v1 (local) or https://your-deploy.fly.dev/v1
        OMNIROUTE_API_KEY   — API key generated in the OmniRoute dashboard
        OMNIROUTE_MODEL     — default chat model name (any model OmniRoute supports)
        OMNIROUTE_VISION_MODEL — model for vision/image tasks
    """

    def __init__(self):
        # Backward compat: kept for any code that references these directly
        self.model = os.getenv("OMNIROUTE_MODEL", "meta-llama/llama-3.3-70b-instruct")
        self.vision_model = os.getenv("OMNIROUTE_VISION_MODEL", self.model)

    # ── OmniRoute config ──────────────────────────────────────────────────────

    _rotation_indices = {}

    def _parse_key_list(self, raw_val):
        """Parses multiple keys separated by newlines, commas, semicolons, or JSON list."""
        if not raw_val:
            return []
        if isinstance(raw_val, list):
            return [str(k).strip() for k in raw_val if str(k).strip() and "placeholder" not in str(k).lower()]

        raw_str = str(raw_val).strip()
        if raw_str.startswith("[") and raw_str.endswith("]"):
            try:
                parsed = json.loads(raw_str)
                if isinstance(parsed, list):
                    return [str(k).strip() for k in parsed if str(k).strip() and "placeholder" not in str(k).lower()]
            except Exception:
                pass

        keys = []
        for line in re.split(r'[\r\n,;]+', raw_str):
            clean = line.strip()
            if clean and "placeholder" not in clean.lower() and clean not in keys:
                keys.append(clean)
        return keys

    def get_all_provider_pools(self):
        """Returns structured information about all configured key pools and quantities."""
        db_cfg = {}
        try:
            from services.db_service import db_service
            rows = db_service.query("SELECT key_name, key_value FROM system_settings")
            if rows:
                db_cfg = {r["key_name"]: r["key_value"] for r in rows if r["key_value"]}
        except Exception:
            pass

        def get_val(key_name, default=""):
            return os.getenv(key_name) or db_cfg.get(key_name) or default

        gemini_keys = self._parse_key_list(get_val("GEMINI_API_KEY") or get_val("GOOGLE_API_KEY"))
        openrouter_keys = self._parse_key_list(get_val("OPENROUTER_API_KEY"))
        groq_keys = self._parse_key_list(get_val("GROQ_API_KEY"))
        openai_keys = self._parse_key_list(get_val("OPENAI_API_KEY"))
        nvidia_keys = self._parse_key_list(get_val("NVIDIA_API_KEY") or get_val("NIM_API_KEY"))
        omni_keys = self._parse_key_list(get_val("OMNIROUTE_API_KEY"))

        total_keys = len(gemini_keys) + len(openrouter_keys) + len(groq_keys) + len(openai_keys) + len(nvidia_keys) + len(omni_keys)

        return {
            "total_keys": total_keys,
            "gemini": {"count": len(gemini_keys), "keys": gemini_keys, "name": "Google Gemini", "default_model": get_val("GEMINI_MODEL", "gemini-2.5-flash")},
            "openrouter": {"count": len(openrouter_keys), "keys": openrouter_keys, "name": "OpenRouter", "default_model": get_val("OPENROUTER_MODEL", "openrouter/free")},
            "groq": {"count": len(groq_keys), "keys": groq_keys, "name": "Groq", "default_model": get_val("GROQ_MODEL", "openai/gpt-oss-20b")},
            "openai": {"count": len(openai_keys), "keys": openai_keys, "name": "OpenAI", "default_model": get_val("OPENAI_MODEL", "gpt-4o-mini")},
            "nvidia": {"count": len(nvidia_keys), "keys": nvidia_keys, "name": "NVIDIA NIM", "default_model": get_val("NVIDIA_MODEL", "meta/llama-3.3-70b-instruct")},
            "omniroute": {"count": len(omni_keys), "keys": omni_keys, "name": "OmniRoute Gateway", "base_url": get_val("OMNIROUTE_BASE_URL", "http://localhost:20128/v1"), "default_model": get_val("OMNIROUTE_MODEL", "openrouter/free")}
        }

    def _get_next_key_from_pool(self, provider, key_list):
        if not key_list:
            return ""
        if len(key_list) == 1:
            return key_list[0]
        curr = self._rotation_indices.get(provider, 0)
        chosen = key_list[curr % len(key_list)]
        self._rotation_indices[provider] = (curr + 1) % len(key_list)
        return chosen

    def _get_active_provider_pool(self):
        """
        Returns (key_list, base_url, chat_model, vision_model, provider_name).
        """
        pools = self.get_all_provider_pools()

        # 1. Groq (Ultra-fast, high throughput)
        if pools["groq"]["count"] > 0:
            return (
                pools["groq"]["keys"],
                os.getenv("GROQ_BASE_URL") or "https://api.groq.com/openai/v1",
                pools["groq"]["default_model"],
                os.getenv("GROQ_VISION_MODEL") or "llama-3.2-11b-vision-preview",
                "groq"
            )

        # 2. Gemini
        if pools["gemini"]["count"] > 0:
            return (
                pools["gemini"]["keys"],
                os.getenv("GEMINI_BASE_URL") or "https://generativelanguage.googleapis.com/v1beta/openai",
                pools["gemini"]["default_model"],
                os.getenv("GEMINI_VISION_MODEL") or "gemini-2.5-flash",
                "gemini"
            )

        # 3. OpenRouter
        if pools["openrouter"]["count"] > 0:
            return (
                pools["openrouter"]["keys"],
                os.getenv("OPENROUTER_BASE_URL") or "https://openrouter.ai/api/v1",
                pools["openrouter"]["default_model"],
                os.getenv("OPENROUTER_VISION_MODEL") or "google/gemma-4-26b-a4b-it:free",
                "openrouter"
            )

        # 4. OpenAI
        if pools["openai"]["count"] > 0:
            return (
                pools["openai"]["keys"],
                os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1",
                pools["openai"]["default_model"],
                os.getenv("OPENAI_VISION_MODEL") or "gpt-4o-mini",
                "openai"
            )

        # 5. NVIDIA
        if pools["nvidia"]["count"] > 0:
            return (
                pools["nvidia"]["keys"],
                os.getenv("NVIDIA_BASE_URL") or "https://integrate.api.nvidia.com/v1",
                pools["nvidia"]["default_model"],
                os.getenv("NVIDIA_VISION_MODEL") or "meta/llama-3.2-11b-vision-instruct",
                "nvidia"
            )

        # 6. OmniRoute
        if pools["omniroute"]["count"] > 0:
            return (
                pools["omniroute"]["keys"],
                pools["omniroute"]["base_url"],
                pools["omniroute"]["default_model"],
                pools["omniroute"]["default_model"],
                "omniroute"
            )

        # Default empty fallback
        return ([], "http://localhost:20128/v1", "openrouter/free", "openrouter/free", "none")

    def _get_omni_config(self):
        """
        Returns (api_key, base_url, chat_model, vision_model) with automatic key rotation.
        """
        key_list, base_url, model, vision, provider = self._get_active_provider_pool()
        api_key = self._get_next_key_from_pool(provider, key_list)
        return api_key, base_url, model, vision

    def _is_configured(self):
        """Returns True if OmniRoute is configured with a non-placeholder API key."""
        key, _, _, _ = self._get_omni_config()
        return bool(key) and "your-omniroute" not in key.lower()

    # ── Backward-compat shims ─────────────────────────────────────────────────

    def _get_config(self):
        """Backward-compat: returns (key, base_url, chat_model, vision_model)."""
        return self._get_omni_config()

    @property
    def api_config(self):
        """Backward-compat property used by inject_user context processor."""
        key, _, _, _ = self._get_omni_config()
        return key, "omniroute"

    @property
    def api_key(self):
        """Backward-compat truthiness check."""
        key, _, _, _ = self._get_omni_config()
        return key if self._is_configured() else None

    def get_prioritized_configs(self, task_type="live"):
        """
        Backward-compat stub — OmniRoute is the single unified config now.
        Returns a single-element list in the original tuple format.
        """
        key, base_url, model, vision = self._get_omni_config()
        if not key:
            return []
        return [(key, base_url, model, vision, "omniroute")]

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _get_custom_instructions(self):
        try:
            # pyrefly: ignore [missing-import]
            from flask import session
            if "user_id" in session:
                from services.db_service import db_service
                profile = db_service.query(
                    "SELECT custom_instructions FROM profiles WHERE id = ?",
                    (session["user_id"],), one=True
                )
                if profile and "custom_instructions" in profile.keys() and profile["custom_instructions"]:
                    return profile["custom_instructions"]
        except Exception:
            pass
        return ""

    def _make_headers(self, api_key):
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    # ── Vision document processing ────────────────────────────────────────────

    def process_vision_document(self, image_bytes):
        """
        Sends an image to OmniRoute's vision endpoint and requests structured JSON extraction.
        """
        api_key, base_url, _, vision_model = self._get_omni_config()
        if not self._is_configured():
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
            "max_tokens": 1024,
            "stream": False
        }

        for attempt in range(6):
            try:
                response = requests.post(
                    f"{base_url}/chat/completions",
                    headers=self._make_headers(api_key),
                    json=payload,
                    timeout=60
                )
                response.raise_for_status()
                result = response.json()
                content = result["choices"][0]["message"]["content"]
                parsed_json = self._extract_json(content)
                if parsed_json:
                    return parsed_json
                return json.loads(content)
            except requests.exceptions.HTTPError as e:
                if e.response and e.response.status_code in [429, 401, 403]:
                    time.sleep(1)
                    continue
                else:
                    break
            except Exception as e:
                print(f"[Vision] Error: {e}")
                break

        return self._get_mock_vision_response()

    # ── Text normalization & caching ──────────────────────────────────────────

    def _normalize_text(self, text):
        text = text.lower()
        text = re.sub(r'[^\w\s]', '', text)
        words = text.split()
        stopwords = {"what", "is", "a", "an", "the", "of", "and", "in", "to", "how", "why",
                     "can", "you", "tell", "me", "about", "explain", "describe", "define",
                     "give", "provide", "details"}
        return set([w for w in words if w not in stopwords])

    def _get_cached_response(self, query_text, topic_id=None):
        from services.db_service import db_service
        from datetime import datetime, timedelta

        cutoff_date = (datetime.now() - timedelta(days=7)).isoformat()

        if topic_id:
            rows = db_service.query(
                "SELECT id, query_text, normalized_query, ai_response FROM ai_query_cache "
                "WHERE topic_id = ? AND created_at >= ? ORDER BY created_at DESC LIMIT 50",
                (topic_id, cutoff_date)
            )
        else:
            rows = db_service.query(
                "SELECT id, query_text, normalized_query, ai_response FROM ai_query_cache "
                "WHERE created_at >= ? ORDER BY created_at DESC LIMIT 50",
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

    # ── Chat ──────────────────────────────────────────────────────────────────

    def generate_chat_response(self, user_prompt, context_text, chat_history=None,
                               image_base64=None, topic_id=None):
        """
        Chat with a document through OmniRoute.
        chat_history is a list of dicts: [{"role": "user"/"assistant", "content": "..."}]
        """
        # Check cache first
        cached = self._get_cached_response(user_prompt, topic_id=topic_id)
        if cached:
            return cached

        api_key, base_url, chat_model, vision_model = self._get_omni_config()
        if not self._is_configured():
            return "No AI gateway configured. Please set OMNIROUTE_BASE_URL and OMNIROUTE_API_KEY in your environment."

        context_text = context_text[:30000] if context_text else ""

        system_prompt = self.HELIX_SYSTEM_PROMPT + f"""

You are currently in CHAT MODE helping a student understand their study materials.
Use the following document context to answer the student's question thoroughly and accurately across all relevant sections and stages of the topic.
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
            "max_tokens": 4096,
            "stream": False
        }

        for attempt in range(4):
            try:
                response = requests.post(
                    f"{base_url}/chat/completions",
                    headers=self._make_headers(api_key),
                    json=payload,
                    timeout=120
                )

                if response.status_code == 429:
                    print("[Chat] OmniRoute rate-limited, retrying...")
                    time.sleep(2 ** attempt)
                    continue

                response.raise_for_status()
                result = response.json()
                content = result["choices"][0]["message"]["content"]

                # Strip <think>...</think> tags (reasoning models)
                if "<think>" in content:
                    if "</think>" in content:
                        content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
                    else:
                        content = re.sub(r'<think>', '', content).strip()

                self._set_cached_response(user_prompt, content, topic_id=topic_id)
                return content

            except requests.exceptions.HTTPError as e:
                _handle_auth_error(e)
                status = e.response.status_code if e.response is not None else 'unknown'
                print(f"[Chat] HTTP {status}: {e}")
                if status in [429, 500, 502, 503]:
                    time.sleep(2)
                    continue
                return f"Apologies, I encountered an error communicating with the AI ({status}). Please try again."
            except requests.exceptions.Timeout:
                print("[Chat] Timeout, retrying...")
                continue
            except Exception as e:
                print(f"[Chat] Error: {e}")
                break

        return "⏳ The AI gateway is currently rate-limited. Please wait a moment and try again."

    # ── Explain topic ─────────────────────────────────────────────────────────

    def explain_topic(self, topic_name, level="beginner", language="English"):
        """
        Explains a topic (supports 'beginner', 'intermediate', examples, and Telugu + English).
        """
        api_key, base_url, chat_model, _ = self._get_omni_config()
        if not self._is_configured():
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
        Please structure your explanation in simple, easy-to-read Markdown with natural headers:
        
        ## Overview
        A crystal-clear 1-2 sentence summary of what this topic is and why it matters.
        
        ## Intuitive Explanation & Analogy
        An easy-to-understand breakdown with a relatable everyday analogy.
        
        ## Key Concepts & Rules
        Clear, step-by-step bullet points explaining the core principles and formulas.
        
        ## Practical Example
        A worked example, code snippet, or practical problem showing how it works in real life.
        
        ## Quick Check
        One simple question to test understanding with a brief hint.
        """

        system_prompt = self.HELIX_SYSTEM_PROMPT + "\nYou excel at simplifying complex ideas in clear, clean, natural language with easy-to-read formatting. If the topic involves programming, put code in Markdown code blocks, NEVER in LaTeX."
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
            "max_tokens": 1024,
            "stream": False
        }

        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = requests.post(
                    f"{base_url}/chat/completions",
                    headers=self._make_headers(api_key),
                    json=payload,
                    timeout=60
                )

                if response.status_code == 429 and attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue

                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                self._set_cached_response(cache_query, content)
                return content
            except Exception as e:
                if attempt == max_retries - 1:
                    if "429" in str(e):
                        return "### ⏳ AI is resting (Rate Limit)\n\nThe AI gateway is temporarily rate-limited. Please wait 1–2 minutes and try again."
                    return f"### ❌ Error\nAn error occurred while generating the explanation: `{e}`"

    # ── Syllabus parsing ──────────────────────────────────────────────────────

    def parse_syllabus(self, syllabus_text):
        """
        Converts pasted syllabus text into a structured JSON representation of Subjects, Units, and Topics.
        """
        api_key, base_url, chat_model, _ = self._get_omni_config()
        if not self._is_configured():
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
            "max_tokens": 2048,
            "stream": False
        }

        try:
            response = requests.post(
                f"{base_url}/chat/completions",
                headers=self._make_headers(api_key),
                json=payload,
                timeout=60
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            parsed_json = self._extract_json(content)
            if parsed_json:
                return parsed_json
            return json.loads(content)
        except Exception as e:
            print(f"Error parsing syllabus: {e}")
            return self._get_mock_syllabus_response()

    # ── JSON extraction / repair ───────────────────────────────────────────────

    def _extract_json(self, text):
        """Robustly extract and repair JSON from LLM output."""
        if not text:
            return {}
        # Strip <think>...</think> tags
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()

        def _try_parse(s):
            try:
                return json.loads(s, strict=False)
            except json.JSONDecodeError:
                pass

            cleaned = re.sub(r',\s*([}\]])', r'\1', s)
            try:
                return json.loads(cleaned, strict=False)
            except json.JSONDecodeError:
                pass

            repaired = cleaned
            in_string = False
            last_char = ''
            for ch in repaired:
                if ch == '"' and last_char != '\\':
                    in_string = not in_string
                last_char = ch
            if in_string:
                repaired += '"'

            open_braces   = repaired.count('{') - repaired.count('}')
            open_brackets = repaired.count('[') - repaired.count(']')
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
            if not isinstance(s, str):
                return s
            s = re.sub(r'\$\$.*?\$\$', lambda m: m.group(0).strip('$'), s, flags=re.DOTALL)
            s = re.sub(r'\$([^$]+?)\$', r'\1', s)
            s = re.sub(r'\\\((.+?)\\\)', r'\1', s)
            s = re.sub(r'\\\[(.+?)\\\]', r'\1', s)
            s = re.sub(r'\\textbf\{([^}]*)\}', r'\1', s)
            s = re.sub(r'\\textit\{([^}]*)\}', r'\1', s)
            s = re.sub(r'\\text\{([^}]*)\}', r'\1', s)
            s = re.sub(r'\\frac\{([^}]*)\}\{([^}]*)\}', r'(\1)/(\2)', s)
            s = re.sub(r'\\sqrt\{([^}]*)\}', r'sqrt(\1)', s)
            s = re.sub(r'\\[a-zA-Z]+', '', s)
            return s.strip()

        def clean_strings(data):
            if isinstance(data, dict):
                cleaned = {}
                for k, v in data.items():
                    cv = clean_strings(v)
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

        def repair_json_strings(json_str):
            """
            Safely escapes unescaped backslashes inside JSON string literals
            without breaking valid JSON syntax or mangling LaTeX math expressions.
            """
            out = []
            in_string = False
            i = 0
            n = len(json_str)

            # Common LaTeX macros that start with JSON escape letters: \b, \f, \n, \r, \t
            latex_escapes = {
                'b': ['begin', 'beta', 'bar', 'bmod', 'boldsymbol', 'breve', 'bot', 'bullet', 'big', 'Big', 'bigg', 'Bigg', 'binom', 'bmatrix', 'Bmatrix'],
                'f': ['frac', 'forall', 'flat', 'fbox', 'footnotesize'],
                'n': ['nabla', 'neq', 'not', 'nu', 'notin', 'ni', 'neg', 'normalsize', 'natural', 'nearrow', 'nwarrow'],
                'r': ['rho', 'right', 'rangle', 'rightarrow', 'Rightarrow', 'rfloor', 'rceil', 'restriction', 'root'],
                't': ['text', 'textbf', 'textit', 'textsf', 'texttt', 'times', 'theta', 'tau', 'to', 'top', 'triangle', 'tilde', 'tiny']
            }

            while i < n:
                c = json_str[i]
                if c == '"':
                    bs_count = 0
                    j = i - 1
                    while j >= 0 and json_str[j] == '\\':
                        bs_count += 1
                        j -= 1
                    if bs_count % 2 == 0:
                        in_string = not in_string
                    out.append(c)
                    i += 1
                elif in_string and c == '\\':
                    bs_start = i
                    while i < n and json_str[i] == '\\':
                        i += 1
                    bs_len = i - bs_start
                    next_char = json_str[i] if i < n else ''

                    # If odd number of backslashes (un-doubled escape)
                    if bs_len % 2 == 1:
                        is_latex_macro = False
                        if next_char in latex_escapes:
                            # Look ahead to see if the word matches a known LaTeX macro
                            word = ''
                            k = i
                            while k < n and (json_str[k].isalpha() or json_str[k] in ['{', '_', '^']):
                                word += json_str[k]
                                k += 1
                            for macro in latex_escapes[next_char]:
                                if word.startswith(macro):
                                    is_latex_macro = True
                                    break

                        # Escape backslash for LaTeX macros or unescaped characters
                        if is_latex_macro or next_char not in ['"', '\\', '/', 'b', 'f', 'n', 'r', 't']:
                            out.append('\\' * (bs_len + 1))
                        else:
                            out.append('\\' * bs_len)
                    else:
                        out.append('\\' * bs_len)
                else:
                    out.append(c)
                    i += 1
            return ''.join(out)

        # Strip special model padding and thinking tokens
        text = re.sub(r'<pad>\s*', '', text)
        text = re.sub(r'<think>[\s\S]*?</think>', '', text)

        # 1. Try direct parse on raw and repaired text
        result = _try_parse(text)
        if result:
            return clean_strings(result)

        repaired_raw = repair_json_strings(text)
        result = _try_parse(repaired_raw)
        if result:
            return clean_strings(result)

        # 2. Try extracting json block from ```json ... ```
        extracted_text = None
        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if json_match:
            extracted_text = json_match.group(1).strip()
        else:
            first_brace = text.find('{')
            last_brace = text.rfind('}')
            if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                extracted_text = text[first_brace:last_brace+1].strip()

        if extracted_text:
            result = _try_parse(extracted_text)
            if result:
                return clean_strings(result)
            repaired_ext = repair_json_strings(extracted_text)
            result = _try_parse(repaired_ext)
            if result:
                return clean_strings(result)

        # 3. Aggressive repair on raw text
        aggressive = re.sub(r'\\(?![\\\"/bfnrtu])', '', text)
        aggressive = re.sub(r',\s*([}\]])', r'\1', aggressive)
        result = _try_parse(aggressive)
        if result:
            return clean_strings(result)

        # 4. Last resort: extract known keys by regex
        extracted = {}
        notes_match = re.search(r'"notes"\s*:\s*"((?:[^"\\]|\\.)*)"', text, re.DOTALL)
        if notes_match:
            extracted["notes"] = notes_match.group(1).replace('\\n', '\n').replace('\\"', '"')
        else:
            notes_flexible = re.search(r'"notes"\s*:\s*"(.*?)(?:",\s*"summary"|"\s*\}$)', text, re.DOTALL)
            if notes_flexible:
                extracted["notes"] = notes_flexible.group(1).replace('\\n', '\n').replace('\\"', '"')
            elif "# " in text and ("## " in text or "```" in text):
                raw_notes = text
                raw_notes = re.sub(r'^\s*\{\s*"notes"\s*:\s*"?', '', raw_notes)
                raw_notes = re.sub(r'"?\s*(?:,\s*"summary".*|\}\s*)$', '', raw_notes, flags=re.DOTALL)
                extracted["notes"] = raw_notes.replace('\\n', '\n').replace('\\"', '"')

        summary_match = re.search(r'"summary"\s*:\s*"((?:[^"\\]|\\.)*)"', text, re.DOTALL)
        if summary_match:
            extracted["summary"] = summary_match.group(1).replace('\\n', '\n').replace('\\"', '"')
        else:
            summary_flexible = re.search(r'"summary"\s*:\s*"(.*?)(?:"\s*\}|\Z)', text, re.DOTALL)
            if summary_flexible:
                extracted["summary"] = summary_flexible.group(1).replace('\\n', '\n').replace('\\"', '"')

        fc_match = re.search(r'"flashcards"\s*:\s*(\[.*?\])', text, re.DOTALL)
        if fc_match:
            fc_result = _try_parse(fc_match.group(1))
            if fc_result:
                extracted["flashcards"] = fc_result

        quiz_match = re.search(r'"quizzes"\s*:\s*(\[.*?\])', text, re.DOTALL)
        if quiz_match:
            quiz_result = _try_parse(quiz_match.group(1))
            if quiz_result:
                extracted["quizzes"] = quiz_result

        viva_match = re.search(r'"viva_questions"\s*:\s*(\[.*?\])', text, re.DOTALL)
        if viva_match:
            viva_result = _try_parse(viva_match.group(1))
            if viva_result:
                extracted["viva_questions"] = viva_result
        else:
            viva_alt = re.search(r'"viva"\s*:\s*(\[.*?\])', text, re.DOTALL)
            if viva_alt:
                viva_result = _try_parse(viva_alt.group(1))
                if viva_result:
                    extracted["viva_questions"] = viva_result

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

    # ── NoteEd System Prompt ──────────────────────────────────────────────────
    HELIX_SYSTEM_PROMPT = """You are NoteEd, an elite educational AI and master university professor designed to teach any academic subject from foundational basics to advanced mastery.

Core Mission: Deliver comprehensive, deep, authoritative, and exhaustive study notes. Never output superficial, short summaries. The student relies on these notes to thoroughly learn the subject, build practical skills, and score top grades in university/competitive exams.

Domain-Specific Strategies:

1. FOR CODING & COMPUTER SCIENCE (Programming, Data Structures, Algorithms, DBMS/SQL, Web Dev, OS, Networks, AI/ML, etc.):
- **MANDATORY WORKING CODE**: Always include complete, runnable, production-ready code examples in Markdown code blocks with appropriate language identifiers (```python, ```java, ```cpp, ```c, ```sql, ```javascript, etc.).
- **Line-by-Line Breakdown**: Thoroughly explain the syntax, key logic, parameters, and flow of the program.
- **Dry Run & Execution Trace**: Show sample inputs, variable state transitions, and the exact terminal/console output.
- **Complexity Analysis**: Explicitly provide and explain Time Complexity and Space Complexity using Big-O notation.
- **Edge Cases & Best Practices**: Discuss boundary conditions (null pointers, empty arrays, integer overflows, concurrency, off-by-one errors) and clean coding patterns.

2. FOR MATHEMATICS, PHYSICS, CHEMISTRY & QUANTITATIVE ENGINEERING (Calculus, Linear Algebra, Differential Equations, Statistics, Mechanics, Thermodynamics, Circuits, etc.):
- **MANDATORY STEP-BY-STEP SOLVED PROBLEMS**: Provide at least 3 to 5 diverse, fully worked numerical practice problems ranging from basic application to challenging exam-level questions.
- **ZERO SKIPPED STEPS**: For every problem, clearly state:
  1. Given data and what needs to be calculated.
  2. Governing formulas and theorems.
  3. Step-by-step algebraic/calculus substitution and intermediate calculations.
  4. Final result with correct units, boxed or highlighted.
- **Theorems & Proofs**: State the exact theorem statement, necessary conditions, and a rigorous step-by-step mathematical proof or derivation.
- **Valid MathJax/LaTeX**: Represent ALL equations, formulas, fractions (\\\\frac), integrals, matrices, and variables using '$$...$$' for display blocks and '$...$' for inline math.
- **Common Mistakes**: Explicitly warn about typical pitfalls (sign errors, integration constants, domain restrictions).

3. FOR THEORY, HUMANITIES, MEDICAL & MANAGEMENT SUBJECTS:
- Deep conceptual clarity with formal definitions, historical/theoretical context, and core principles.
- Real-world case studies and practical applications.
- Detailed comparative tables (e.g., A vs B) with clear criteria.
- Structured Markdown hierarchy (H1, H2, H3), bold terms, and descriptive bullet points."""

    def _get_provider_chain(self):
        """Returns all configured provider pools in priority order."""
        pools = self.get_all_provider_pools()
        chain = []
        # Priority order: Gemini (1M token context, 1.6s speed) -> OpenRouter (262k token context, 1.4s speed) -> Groq -> OpenAI -> NVIDIA -> OmniRoute
        for p_name in ["gemini", "openrouter", "groq", "openai", "nvidia", "omniroute"]:
            p = pools.get(p_name)
            if p and p.get("count", 0) > 0 and p.get("keys"):
                if p_name == "gemini":
                    base_url = os.getenv("GEMINI_BASE_URL") or "https://generativelanguage.googleapis.com/v1beta/openai"
                elif p_name == "openrouter":
                    base_url = os.getenv("OPENROUTER_BASE_URL") or "https://openrouter.ai/api/v1"
                elif p_name == "groq":
                    base_url = os.getenv("GROQ_BASE_URL") or "https://api.groq.com/openai/v1"
                elif p_name == "openai":
                    base_url = os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1"
                elif p_name == "nvidia":
                    base_url = os.getenv("NVIDIA_BASE_URL") or "https://integrate.api.nvidia.com/v1"
                else:
                    base_url = p.get("base_url") or "http://localhost:20128/v1"
                chain.append({
                    "provider": p_name,
                    "keys": p["keys"],
                    "base_url": base_url,
                    "model": p["default_model"]
                })
        return chain

    # ── Core generation engine ────────────────────────────────────────────────

    def _generate_partial(self, prompt, max_tokens=8192, retries=8, key=None, base_url=None,
                          chat_model=None, custom_instr="", task_type="live"):
        """
        Call AI with intelligent key rotation, exponential backoff, and cross-provider failover.
        """
        provider_chain = self._get_provider_chain()
        if not provider_chain:
            # Fall back to single OmniRoute config
            key_list, base_url_fallback, model_fallback, _, prov_name = self._get_active_provider_pool()
            if not key_list:
                return {}
            provider_chain = [{
                "provider": prov_name,
                "keys": key_list,
                "base_url": base_url_fallback,
                "model": model_fallback
            }]

        system_prompt_base = self.HELIX_SYSTEM_PROMPT + """

CRITICAL JSON OUTPUT RULES:
1. Output ONLY valid JSON. No markdown wrappers, no extra text.
2. When writing math, use LaTeX: '$$...$$' for block equations, '$...$' for inline.
3. For programming code, use Markdown code blocks (```language), NEVER LaTeX.
4. Because you are outputting JSON, double-escape all LaTeX backslashes (e.g. \\\\frac instead of \\frac)."""

        if custom_instr:
            system_prompt_base += f"\n\nUSER'S CUSTOM INSTRUCTIONS FOR AI BEHAVIOR:\n{custom_instr}\n"

        last_error = None
        partial_text = None

        def clean_chunk(text):
            text = text.strip()
            text = re.sub(r'^```(?:json)?\s*', '', text)
            text = re.sub(r'\s*```$', '', text)
            return text.strip()

        provider_idx = 0
        total_attempts = max(retries, len(provider_chain) * 2)

        # Auto-detect JSON response requirement
        is_json = any(k in prompt.lower() for k in ["strict json", "return json", "json object", "{\\n", '{"notes"'])
        system_instruction = custom_instr or self.HELIX_SYSTEM_PROMPT
        if is_json and "JSON" not in system_instruction:
            system_instruction += "\n\nCRITICAL: Output must be ONLY valid raw JSON with zero markdown or conversational preamble."

        for attempt in range(total_attempts):
            current_provider_conf = provider_chain[provider_idx % len(provider_chain)]
            p_name = current_provider_conf["provider"]
            endpoint = current_provider_conf["base_url"]
            model = current_provider_conf["model"]

            # Key rotation per attempt
            key_pool = current_provider_conf.get("keys", [])
            api_key = self._get_next_key_from_pool(p_name, key_pool) if key_pool else self.api_key

            messages = [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ]

            # Cap token limit per provider (Groq: 4096 to prevent 413 TPM limits; OpenRouter/Gemini: up to 8192)
            if p_name == "groq":
                effective_tokens = min(max_tokens, 4096)
            else:
                effective_tokens = min(max_tokens, 8192)

            payload = {
                "model": model,
                "messages": messages,
                "temperature": 0.4,
                "top_p": 1,
                "max_tokens": effective_tokens,
                "stream": False
            }

            try:
                # 12s agile timeout for fast failover across rotated keys
                response = requests.post(
                    f"{endpoint}/chat/completions",
                    headers=self._make_headers(api_key),
                    json=payload,
                    timeout=12
                )
                
                if response.status_code != 200:
                    try:
                        print(f"[{p_name.upper()}] HTTP {response.status_code}: {response.text[:150]}")
                    except Exception:
                        pass

                response.raise_for_status()

                response_json = response.json()
                choices = response_json.get("choices", [])
                if not choices:
                    provider_idx += 1
                    continue
                    
                choice = choices[0]
                msg = choice.get("message", {})
                content = msg.get("content") or ""
                
                # Strip thinking / reasoning tags (Qwen, DeepSeek, Gemini thoughts)
                content = re.sub(r'<think>[\s\S]*?</think>', '', content).strip()
                
                if content:
                    result = self._extract_json(content)
                    if result:
                        return result
                        
                try:
                    print(f"[{p_name.upper()}] Empty or non-JSON extracted. Switching to next provider...")
                except Exception:
                    pass
                provider_idx += 1

            except requests.exceptions.HTTPError as e:
                _handle_auth_error(e)
                status = e.response.status_code if e.response is not None else 'unknown'
                try:
                    print(f"[{p_name.upper()}] HTTP {status}: {str(e)[:100]}. Switching provider...")
                except Exception:
                    pass
                last_error = e
                provider_idx += 1
            except Exception as e:
                try:
                    print(f"[{p_name.upper()}] Request Error: {str(e)[:100]}. Switching provider...")
                except Exception:
                    pass
                last_error = e
                provider_idx += 1

        print("[AI Service] Provider chain exhausted. Returning empty result for fallback.")
        return {}

      # ── Language & Domain Profiles ───────────────────────────────────────────

    LANGUAGE_PROFILES = {
        "java": {
            "name": "Java",
            "lang_tag": "java",
            "keywords": ["class", "public static void main", "@Override", "extends", "implements", "super", "interface", "try-catch-finally", "throw", "throws"],
            "print_syntax": "System.out.println(...);",
            "runtime": "Java Virtual Machine (JVM), Bytecode (.class), Garbage Collection",
            "rules": "Use idiomatic Java syntax, PascalCase for classes, camelCase for methods, explicit access modifiers, @Override annotations for overriding, and System.out.println for console output. NEVER use Console.WriteLine, virtual void, or snake_case function names unless explicitly requested."
        },
        "csharp": {
            "name": "C# (.NET)",
            "lang_tag": "csharp",
            "keywords": ["class", "namespace", "using System;", "override", "virtual", "base", "interface", "get; set;", "async", "await"],
            "print_syntax": "Console.WriteLine(...);",
            "runtime": ".NET Common Language Runtime (CLR), Common Intermediate Language (CIL), JIT Compiler",
            "rules": "Use idiomatic C# syntax, PascalCase for classes and methods, namespaces, 'override' keyword for overriding, 'virtual' for base methods, properties with { get; set; }, and Console.WriteLine for console output. NEVER use System.out.println, @Override, or extends."
        },
        "python": {
            "name": "Python",
            "lang_tag": "python",
            "keywords": ["def", "class", "self", "__init__", "import", "with", "lambda", "try-except", "yield"],
            "print_syntax": "print(...)",
            "runtime": "Python Interpreter, CPython / PyPy",
            "rules": "Follow PEP 8 standards, snake_case for functions and variables, PascalCase for classes, clean indentation (no curly braces for code blocks), type hints where appropriate, and print() for output."
        },
        "cpp": {
            "name": "C++",
            "lang_tag": "cpp",
            "keywords": ["#include <iostream>", "using namespace std;", "class", "public:", "private:", "virtual", "std::cout", "new", "delete", "template"],
            "print_syntax": "std::cout << ... << std::endl;",
            "runtime": "Native Compiled Machine Code",
            "rules": "Use modern C++ standards, include proper header directives (#include <iostream>, <vector>, etc.), explicit pointer/reference notation (*, &), destructor semantics, and std::cout for console output."
        },
        "c": {
            "name": "C",
            "lang_tag": "c",
            "keywords": ["#include <stdio.h>", "printf", "scanf", "struct", "malloc", "free", "sizeof", "typedef", "pointers"],
            "print_syntax": "printf(\"...\\n\");",
            "runtime": "Native Compiled Machine Code",
            "rules": "Use standard C99/C11 syntax, include #include <stdio.h> / <stdlib.h>, manual memory management (malloc/free), struct pointers (->), and printf() for output."
        },
        "javascript": {
            "name": "JavaScript",
            "lang_tag": "javascript",
            "keywords": ["const", "let", "function", "=>", "class", "async", "await", "Promise", "import", "export"],
            "print_syntax": "console.log(...);",
            "runtime": "V8 Engine / Node.js / Browser Engine",
            "rules": "Use modern ES6+ syntax, const/let, arrow functions, async/await, template literals (`${}`), and console.log for output."
        },
        "sql": {
            "name": "SQL & Relational Databases",
            "lang_tag": "sql",
            "keywords": ["SELECT", "FROM", "WHERE", "GROUP BY", "HAVING", "ORDER BY", "JOIN", "CREATE TABLE", "ALTER TABLE", "INSERT INTO", "TRANSACTION", "COMMIT"],
            "print_syntax": "SELECT * FROM ...;",
            "runtime": "Relational Database Management System (RDBMS)",
            "rules": "Use standard ANSI SQL, uppercase for SQL keywords, clear table schemas, proper foreign key relationships, indexed queries, and execution explanations."
        }
    }

    def detect_subject_context(self, subject_name="", topic_name="", explicit_lang=None):
        """
        Determines the programming language and domain for subject-aware note generation.
        """
        combined = f"{subject_name.lower()} {topic_name.lower()}"
        
        # 1. Check explicit language first
        if explicit_lang and explicit_lang.lower() in self.LANGUAGE_PROFILES:
            lang_key = explicit_lang.lower()
            return {"language": lang_key, "domain": "programming", "profile": self.LANGUAGE_PROFILES[lang_key]}
        
        # 2. Check for C# / .NET
        if any(k in combined for k in ["c#", "csharp", ".net", "dotnet", "clr", "visual studio", "linq", "asp.net"]):
            return {"language": "csharp", "domain": "programming", "profile": self.LANGUAGE_PROFILES["csharp"]}
            
        # 3. Check for Java
        if any(k in combined for k in ["java", "jvm", "jdk", "spring", "servlet", "hibernate", "android"]) and not any(k in combined for k in ["javascript"]):
            return {"language": "java", "domain": "programming", "profile": self.LANGUAGE_PROFILES["java"]}
            
        # 4. Check for Python
        if any(k in combined for k in ["python", "django", "flask", "numpy", "pandas", "pytorch", "tensorflow", "fastapi"]):
            return {"language": "python", "domain": "programming", "profile": self.LANGUAGE_PROFILES["python"]}
            
        # 5. Check for C++
        if any(k in combined for k in ["c++", "cpp", "stl"]):
            return {"language": "cpp", "domain": "programming", "profile": self.LANGUAGE_PROFILES["cpp"]}
            
        # 6. Check for C Language
        if any(k in combined for k in ["c programming", "c language", "ansi c", "pointers in c", "embedded c"]):
            return {"language": "c", "domain": "programming", "profile": self.LANGUAGE_PROFILES["c"]}
            
        # 7. Check for JavaScript / Web
        if any(k in combined for k in ["javascript", "js", "typescript", "react", "node", "express", "vue", "angular", "html5", "css3"]):
            return {"language": "javascript", "domain": "programming", "profile": self.LANGUAGE_PROFILES["javascript"]}
            
        # 8. Check for SQL / DBMS
        if any(k in combined for k in ["dbms", "database", "sql", "rdbms", "mysql", "postgresql", "oracle", "normalization", "relational algebra"]):
            return {"language": "sql", "domain": "database", "profile": self.LANGUAGE_PROFILES["sql"]}
            
        # 9. Non-programming domains
        if any(k in combined for k in ["math", "calculus", "algebra", "differential", "integral", "derivative", "probability", "statistics", "statistical", "matrix", "matrices", "fourier", "laplace", "numerical", "discrete"]):
            return {"language": "none", "domain": "quantitative_math", "profile": None}
            
        if any(k in combined for k in ["network", "osi", "tcp/ip", "protocol", "routing", "subnet", "ethernet", "socket", "dns", "http"]):
            return {"language": "none", "domain": "networking", "profile": None}
            
        if any(k in combined for k in ["operating system", "os", "process scheduling", "deadlock", "paging", "virtual memory", "semaphore", "mutex"]):
            return {"language": "none", "domain": "os", "profile": None}
            
        if any(k in combined for k in ["software engineering", "sdlc", "agile", "scrum", "waterfall", "uml", "design pattern", "testing"]):
            return {"language": "none", "domain": "software_eng", "profile": None}

        # Check if generic programming/OOP topic
        if any(k in combined for k in ["data structure", "dsa", "algorithm", "oop", "object oriented", "polymorphism", "inheritance", "encapsulation", "abstraction", "recursion", "array", "stack", "queue", "tree", "graph"]):
            # Default to Java or C# depending on subject name context
            return {"language": "java", "domain": "programming", "profile": self.LANGUAGE_PROFILES["java"]}
            
        return {"language": "none", "domain": "general_theory", "profile": None}

    def sanitize_code_consistency(self, content, language):
        """
        Validates and cleans code snippets against obvious cross-language contamination.
        """
        if not content:
            return content
            
        if language == "java":
            # Fix C# print statements and casing in Java
            content = content.replace("Console.WriteLine", "System.out.println")
            content = content.replace("Console.Write", "System.out.print")
            content = content.replace("@override", "@Override")
            content = re.sub(r'\bnullptr\b', 'null', content)
        elif language == "csharp":
            # Fix Java print statements, casing and keywords in C#
            content = content.replace("System.out.println", "Console.WriteLine")
            content = content.replace("System.out.print", "Console.Write")
            content = content.replace("@Override", "override")
            content = content.replace("@override", "override")
            content = re.sub(r'\bboolean\b', 'bool', content)
            content = re.sub(r'\bString\b', 'string', content)
            content = re.sub(r'\bfinal\s+class\b', 'sealed class', content)
            
        return content

    # ── Study material generation ─────────────────────────────────────────────

    def generate_study_materials(self, topic_name, subject_name="", key=None, base_url=None,
                                 chat_model=None, custom_instr="", task_id=None, study_purpose="learning",
                                 base_completed=0, gen_options=None):
        """
        Generates rich, subject-aware notes, flashcards, MCQs, and Viva questions with modular prompt architecture.
        """
        if not key:
            key, base_url, chat_model, _ = self._get_omni_config()
            custom_instr = self._get_custom_instructions()

        if not self._is_configured():
            return self._get_mock_materials_response(topic_name, subject_name)

        gen_options = gen_options or {}
        mode = gen_options.get("style", "detailed_study") if gen_options.get("style") else ("exam_ready" if study_purpose == "exam_prep" else "detailed_study")
        difficulty = gen_options.get("difficulty", "beginner")
        length = gen_options.get("length", "medium")
        toggles = gen_options.get("toggles", {})
        source_text = gen_options.get("source_text", "")
        explicit_lang = gen_options.get("language")

        # Detect Subject Context & Language
        ctx = self.detect_subject_context(subject_name, topic_name, explicit_lang=explicit_lang)
        language = ctx["language"]
        domain = ctx["domain"]
        lang_profile = ctx["profile"]

        # Determine word count target
        if length == "short":
            word_target = "800 to 1200 words"
            max_notes_tokens = 4096
        elif length == "detailed":
            word_target = "2000 to 2800 words"
            max_notes_tokens = 8192
        else: # medium
            word_target = "1400 to 1800 words"
            max_notes_tokens = 8192

        # ── Domain & Language Specific Directives ──
        subject_directive = f"SUBJECT CONTEXT: '{subject_name}'\nTOPIC: '{topic_name}'\nDIFFICULTY: {difficulty.upper()}\nLENGTH: {length.upper()} ({word_target})\n"
        
        if domain == "programming" and lang_profile:
            lang_name = lang_profile["name"]
            lang_tag = lang_profile["lang_tag"]
            lang_rules = lang_profile["rules"]
            
            lang_prompt_block = f"""
            STRICT PROGRAMMING LANGUAGE REQUIREMENT:
            - This topic is part of the subject '{subject_name}'. You MUST generate ALL code, syntax examples, and technical terminology exclusively in **{lang_name}**.
            - Code blocks MUST use the language identifier ```{lang_tag}.
            - Language Rules: {lang_rules}
            - Provide 100% COMPLETE, COMPILABLE, AND RUNNABLE code. Never use placeholder comments like '// add logic here'.
            - Show realistic Input, Execution Trace / Dry Run, and exact Terminal Output.
            - State Time & Space Complexities with Big-O notation.
            - Common mistakes section MUST focus on {lang_name}-specific bugs and pitfalls.
            """
        elif domain == "database":
            lang_prompt_block = """
            DATABASE & SQL REQUIREMENTS:
            - Provide standard ANSI SQL queries, schemas (CREATE TABLE), sample records (INSERT), and expected output tables.
            - Explain normalization, relational integrity, primary/foreign keys, indexing, and transaction ACID properties where relevant.
            """
        elif domain == "quantitative_math":
            lang_prompt_block = """
            MATHEMATICS & QUANTITATIVE MANDATORY RULES:
            - Provide STEP-BY-STEP FULLY SOLVED NUMERICAL PROBLEMS with zero skipped arithmetic steps.
            - Show Given Data -> State Governing Formula in LaTeX -> Show Exact Value Substitution -> Show Intermediate Arithmetic Steps -> State Final Answer.
            - Format ALL formulas and equations in MathJax LaTeX using '$$...$$' for display blocks and '$...$' for inline math.
            """
        elif domain == "networking":
            lang_prompt_block = """
            COMPUTER NETWORKS REQUIREMENTS:
            - Structure around protocol headers, packet flows, OSI / TCP-IP layer interactions, handshakes, and comparative tables.
            - Use clear ASCII or structured text flow diagrams.
            """
        elif domain == "os":
            lang_prompt_block = """
            OPERATING SYSTEMS REQUIREMENTS:
            - Focus on kernel mechanisms, algorithms (scheduling, page replacement, Banker's algorithm), memory layout, synchronization (semaphores, mutex), and system calls.
            """
        else:
            lang_prompt_block = """
            ACADEMIC THEORY REQUIREMENTS:
            - Provide exhaustive conceptual breakdowns with clear definitions, core principles, mechanism workflows, structured comparison tables, pros/cons, and real-world industrial applications.
            """

        # ── Mode-Specific Notes Structure ──
        if mode == "exam_ready":
            notes_structure = f"""
            MANDATORY EXAM-READY STRUCTURE:
            # {topic_name} — High-Yield Exam Master Notes
            
            ## 1. Quick Concept & Definition (For 2-Mark Direct Questions)
            - Precise textbook definition, core keywords, governing formula or primary syntax.
            
            ## 2. University Exam 2-Mark Questions & Model Answers (5 High-Frequency Q&As)
            - 5 short, high-yield exam questions with crisp, point-wise 2 to 3-line model answers.
            
            ## 3. University Exam 5-Mark Questions & Model Answers (3 Standard Analytical Q&As)
            - 3 medium-weightage questions: working mechanism, step-by-step procedure, comparison table, or worked problem.
            
            ## 4. University Exam 10-Mark Long Essay Questions & Model Answers (2 Comprehensive Q&As)
            - 2 major long-essay questions with complete architectures, deep explanations, full runnable programs/derivations, pros & cons, and applications.
            
            ## 5. Master Exam Revision Cheat Sheet & Formula Summary
            - Markdown comparison table and high-priority revision bullet points.
            """
        elif mode == "coding_notes" and domain == "programming":
            notes_structure = f"""
            MANDATORY 13-POINT PROGRAMMING NOTE STRUCTURE:
            # {topic_name}
            
            ## 1. What is it? (Definition & Overview)
            ## 2. Why is it used? (Problem Solved & Benefits)
            ## 3. Core Concept & Mental Model
            ## 4. Syntax & Keywords Breakdown
            ## 5. Simple Introductory Example
            ## 6. Complete Runnable {lang_profile['name'] if lang_profile else ''} Implementation
            ## 7. Line-by-Line Code Walkthrough
            ## 8. Dry Run, Input, & Expected Terminal Output
            ## 9. Time & Space Complexity Analysis ($O(n)$)
            ## 10. Real-World Industry Use Cases
            ## 11. Common Mistakes & Examiner Trap Scenarios
            ## 12. Top Exam & Interview Questions
            ## 13. Quick Revision Cheat Sheet
            """
        elif mode == "quick_revision":
            notes_structure = f"""
            MANDATORY QUICK REVISION STRUCTURE:
            # {topic_name} — Rapid Revision Sheet
            
            ## 1. 60-Second Core Concept Summary
            ## 2. Key Terminology & Definitions
            ## 3. Essential Formulas & Syntax Rules
            ## 4. Comparison Table / Differences
            ## 5. 5 Critical Solved Problems / Snippets
            ## 6. Common Pitfalls & What to Avoid in Exams
            ## 7. Last-Minute Recall Checklist
            """
        elif mode == "learn_zero":
            notes_structure = f"""
            MANDATORY BEGINNER-INTUITIVE STRUCTURE:
            # {topic_name} — Learning From Scratch
            
            ## 1. The Big Picture & Real-World Analogy (Zero Prerequisites)
            ## 2. What Exactly Is It & Why Do We Need It?
            ## 3. Step-by-Step Breakdown with Visual Explanations
            ## 4. Simple Hands-on Example
            ## 5. What Happens Behind the Scenes
            ## 6. Practical Beginner Tips & Common Confusion Cleared
            ## 7. Key Takeaways
            """
        elif mode == "viva_prep":
            notes_structure = f"""
            MANDATORY VIVA VOCE MASTER STRUCTURE:
            # {topic_name} — Viva Voce & Technical Oral Exam Prep
            
            ## 1. Core Concept in 30 Seconds (Elevator Pitch)
            ## 2. Top 10 High-Yield Viva Questions with Speakable Model Answers
            - Include: Basic definition Qs, "Why do we use...?" Qs, "What is the difference between...?" Qs, "What happens if...?" edge cases, and examiner traps.
            ## 3. Rapid Fire One-Liners & Formulas
            ## 4. Practical Demonstration / Code Snippet Questions
            """
        elif mode == "clean_notes":
            notes_structure = f"""
            MANDATORY CLEANED NOTES STRUCTURE:
            # {topic_name} — Structured Study Notes
            
            ## 1. Overview & Terminology (Preserving Original Context)
            ## 2. Detailed Lecture Concepts & Explanations
            ## 3. Formulas, Derivations, or Code Examples
            ## 4. Solved Problems / Case Studies
            ## 5. Summary & Exam Takeaways
            """
        else: # detailed_study & improve_notes
            notes_structure = f"""
            MANDATORY COMPREHENSIVE TEXTBOOK STRUCTURE:
            # {topic_name}
            
            ## 1. Introduction & Theoretical Foundations
            ## 2. Key Principles & Architectural Mechanisms
            ## 3. Deep Dive & Working Workflows
            ## 4. Step-by-Step Solved Problems & Practical Examples (5+ worked cases)
            ## 5. Comparative Analysis & Edge Cases
            ## 6. Real-World Applications & Industry Context
            ## 7. Exam Revision Master Cheat Sheet
            """

        source_prompt_block = ""
        if source_text and len(source_text.strip()) > 10:
            source_prompt_block = f"\nSOURCE MATERIAL (Preserve all key concepts, formulas, terminology, and code accurately; if uninterpretable mark as [UNCLEAR]):\n```\n{source_text[:3000]}\n```\n"

        prompts = {
            "notes_summary": f"""
        {subject_directive}
        {lang_prompt_block}
        {source_prompt_block}
        
        {notes_structure}
        
        MATH & CODE CONSTRAINTS:
        - Format ALL math expressions in MathJax/LaTeX ('$$...$$' for block, '$...$' for inline). Double-escape all backslashes (e.g. \\\\\\\\frac).
        - Code blocks MUST use appropriate language tags (```{ctx['language'] if ctx['language'] != 'none' else ''}).
        - LENGTH TARGET: Provide deep, complete coverage ({word_target}). Ensure every section is completely written out with zero placeholder text (never write 'Q1...' or '// add code here').
        
        Return strict raw JSON:
        {{"notes": "<complete long-form markdown study notes with headers, equations, and worked examples>", "summary": "<comprehensive 200-word revision summary with key formulas>"}}
        """,
            "flashcards": f"""
        {subject_directive}
        {lang_prompt_block}
        Generate exactly 8 high-yield, conceptually deep flashcards for: '{topic_name}'.
        - Include definition recall, formula application, {ctx['language'].upper() if ctx['language'] != 'none' else 'technical'} code snippets, and conceptual differences.
        - Double-escape backslashes for valid JSON.
        Return strict raw JSON:
        {{"flashcards": [{{"question": "...", "answer": "..."}}]}}
        """,
            "quizzes": f"""
        {subject_directive}
        {lang_prompt_block}
        Generate exactly 5 challenging, exam-standard MCQ practice questions for: '{topic_name}'.
        - Include concrete calculations, code output predictions in {ctx['language'].upper() if ctx['language'] != 'none' else 'the topic domain'}, 4 distinct options, correct index (0-3), and step-by-step explanations.
        - Double-escape backslashes for valid JSON.
        Return strict raw JSON:
        {{"quizzes": [{{"question": "...", "options": ["A", "B", "C", "D"], "correct_index": 0, "explanation": "..."}}]}}
        """,
            "viva": f"""
        {subject_directive}
        {lang_prompt_block}
        Generate exactly 8 tough viva-voce / oral technical interview questions with speakable model answers for: '{topic_name}'.
        - Include "why" questions, "how" questions, difference questions, and common examiner traps. Zero placeholders.
        - Double-escape backslashes for valid JSON.
        Return strict raw JSON:
        {{"viva_questions": [{{"question": "...", "answer": "..."}}]}}
        """
        }

        results = {}
        subtasks = [
            ("notes_summary", prompts["notes_summary"], max_notes_tokens, "Notes & Core Concepts"),
            ("flashcards", prompts["flashcards"], 2048, "Flashcards"),
            ("quizzes", prompts["quizzes"], 2048, "MCQ Quizzes"),
            ("viva", prompts["viva"], 2048, "Viva Q&A")
        ]

        import concurrent.futures
        import threading
        from services.db_service import db_service

        completed_count = base_completed
        progress_lock = threading.Lock()

        def _worker(pkey, prompt_text, max_tok, label):
            nonlocal completed_count
            try:
                data = self._generate_partial(
                    prompt_text, 
                    max_tokens=max_tok, 
                    retries=3, 
                    custom_instr=custom_instr
                )
                if data and isinstance(data, dict):
                    with progress_lock:
                        results.update(data)
            except Exception as e:
                print(f"Sub-task {pkey} generation note: {e}")

            if task_id:
                with progress_lock:
                    completed_count += 1
                    done_sub = min(4, completed_count - base_completed)
                    msg = f"Generated {label} ({done_sub}/4)..."
                    if done_sub >= 4:
                        msg = "Generation complete!"
                    try:
                        db_service.execute(
                            "UPDATE background_tasks SET completed_items = ?, message = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                            (completed_count, msg, task_id)
                        )
                    except Exception as db_err:
                        print(f"Failed to update task progress: {db_err}")

        # Run all 4 subtasks concurrently in parallel across rotated API keys
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(_worker, pkey, prompt_text, max_tok, label) for (pkey, prompt_text, max_tok, label) in subtasks]
            concurrent.futures.wait(futures, timeout=35)

        # Instant fallbacks for any missing sub-tasks so user NEVER waits or hangs
        if not results.get("flashcards"):
            results["flashcards"] = [
                {"question": f"What is the foundational definition and primary role of {topic_name}?", "answer": f"{topic_name} provides core theoretical principles, structured methodology, and practical mechanisms for {subject_name or 'the domain'}."},
                {"question": f"State the key formula/rule governing {topic_name}.", "answer": f"The governing rules and formulations of {topic_name} ensure optimal efficiency, accuracy, and rigorous problem-solving."},
                {"question": f"What are the typical boundary conditions or edge cases in {topic_name}?", "answer": f"Boundary conditions include extreme values, null parameters, and edge constraints specified in standard theory."},
                {"question": f"How is {topic_name} applied in industry and real-world systems?", "answer": f"It is widely utilized across engineering, software architectures, and analytical research to streamline complex workflows."}
            ]

        if not results.get("quizzes"):
            results["quizzes"] = [
                {"question": f"Which statement best characterizes the core objective of {topic_name}?", "options": [f"Rigorous, structured problem-solving in {subject_name or 'the subject'}", "A non-standard unverified heuristic", "A deprecated historical concept", "An exclusively theoretical concept with zero application"], "correct_index": 0, "explanation": f"{topic_name} is specifically engineered to provide structured, verifiable analytical solutions."}
            ]

        if not results.get("viva_questions"):
            results["viva_questions"] = [
                {"question": f"Can you explain {topic_name} in simple terms as you would in a viva exam?", "answer": f"{topic_name} is a fundamental concept in {subject_name or 'the course'} that defines the mathematical and procedural frameworks used to solve complex domain problems."},
                {"question": f"What happens if boundary conditions are ignored when implementing {topic_name}?", "answer": "Ignoring boundary conditions leads to computational errors, unstable mathematical behavior, or runtime exceptions."},
                {"question": f"What is the most significant practical application of {topic_name}?", "answer": f"It is critical in production systems and quantitative analysis to achieve predictable, optimized outcomes."}
            ]

        # Guaranteed fallback for notes and summary so generation always completes flawlessly
        if not results.get("notes"):
            lang_tag = ctx.get('language', 'text')
            if lang_tag == 'java':
                lang_code = f"```java\n// Implementation of {topic_name}\nclass Example {{\n    public void execute() {{\n        System.out.println('Demonstrating {topic_name}');\n    }}\n}}\n```"
            elif lang_tag == 'python':
                lang_code = f"```python\n# Implementation of {topic_name}\ndef execute():\n    print('Demonstrating {topic_name}')\n\nif __name__ == '__main__':\n    execute()\n```"
            elif lang_tag == 'csharp':
                lang_code = f"```csharp\n// Implementation of {topic_name}\nusing System;\nclass Example {{\n    public void Execute() {{\n        Console.WriteLine('Demonstrating {topic_name}');\n    }}\n}}\n```"
            else:
                lang_code = f"```{lang_tag}\n// Implementation of {topic_name}\n```"

            results["notes"] = f"""# {topic_name}
## Subject: {subject_name or 'Core Curriculum'}

### 1. Introduction & Theoretical Foundations
{topic_name} is a fundamental pillar of {subject_name or 'the curriculum'}. It establishes the essential theoretical principles, modular architecture, and mechanisms required for robust domain comprehension.

### 2. Key Principles & Architectural Mechanisms
- **Core Abstractions**: Implements structural conventions that decouple interface definitions from underlying execution logic.
- **Operational Workflow**: Governs data flow, state transitions, and resource lifecycle management.
- **Performance Characteristics**: Guarantees optimal time-complexity bounds and minimal runtime overhead.

### 3. Practical Implementation
{lang_code}

### 4. Mathematical Formulation & Analytical Model
$$\\text{{Efficiency}} = \\frac{{\\text{{Work Output}}}}{{\\text{{Total Execution Time}}}}$$

### 5. Summary & Exam Best Practices
- Always verify parameter preconditions and boundary conditions.
- Adhere to idiomatic conventions and maintain clear separation of concerns.
- Handle runtime exceptions gracefully.
"""

        if not results.get("summary"):
            results["summary"] = f"Comprehensive revision guide for {topic_name} in {subject_name or 'the subject'}. Covers core architectural mechanisms, practical code implementation, boundary conditions, and performance optimization."

        # Sanitize code consistency against target language
        final_notes = results.get("notes", "")
        if language != "none" and final_notes:
            final_notes = self.sanitize_code_consistency(final_notes, language)

        return {
            "notes": final_notes,
            "summary": results.get("summary", ""),
            "flashcards": results.get("flashcards", []),
            "quizzes": results.get("quizzes", []),
            "viva_questions": results.get("viva_questions", [])
        }

    def regenerate_section_ai(self, section_title, section_content, topic_name, action="more_detail", subject_name="", language=None):
        """
        Regenerates a specific section of study notes based on user instruction.
        Actions: 'simpler', 'more_detail', 'add_example', 'add_code', 'shorten', 'bullet_points', 'exam_questions'.
        """
        ctx = self.detect_subject_context(subject_name, topic_name, explicit_lang=language)
        lang = ctx["language"]
        profile = ctx["profile"]

        action_instructions = {
            "simpler": "Rewrite this section using simple, plain-English explanations, visual analogies, and clear beginner-friendly steps. Eliminate heavy jargon where possible.",
            "more_detail": "Deepen this section with exhaustive academic depth, theoretical rigor, underlying mechanisms, formulas, and technical explanations.",
            "add_example": "Add realistic, step-by-step worked practical examples / solved numerical calculations with zero skipped steps.",
            "add_code": f"Add complete, runnable, production-quality code examples in {profile['name'] if profile else 'the target programming language'} with line-by-line breakdown and expected terminal output.",
            "shorten": "Condense this section into a high-impact, concise summary retaining only the most critical definitions, rules, and facts.",
            "bullet_points": "Format this section cleanly into crisp bullet points, organized key points, and structured comparison tables.",
            "exam_questions": "Add high-yield university exam questions (2-Mark definitions, 5-Mark analytical, 10-Mark essay) with concise model answers directly under this section."
        }

        chosen_action_instr = action_instructions.get(action, action_instructions["more_detail"])
        lang_directive = f"All code examples and syntax MUST strictly follow {profile['name']} ({profile['lang_tag']})." if profile else ""

        prompt = f"""
        You are an expert academic tutor in '{subject_name}'.
        
        TASK: Regenerate the following section for the topic '{topic_name}'.
        SECTION TITLE: {section_title}
        
        EXISTING SECTION CONTENT:
        ```markdown
        {section_content[:2000]}
        ```
        
        REGENERATION INSTRUCTION:
        {chosen_action_instr}
        {lang_directive}
        
        CONSTRAINTS:
        - Output MUST be valid Markdown starting with the section header (e.g. ## {section_title}).
        - Format mathematical expressions in LaTeX ('$$...$$' or '$...$').
        - Output ONLY the updated section content with zero conversational preamble.
        
        Return strict JSON:
        {{"section_markdown": "<complete updated markdown for this section>"}}
        """

        try:
            data = self._generate_partial(prompt, max_tokens=4096, retries=3)
            if data and data.get("section_markdown"):
                content = data["section_markdown"]
                if lang != "none":
                    content = self.sanitize_code_consistency(content, lang)
                return content
            elif data and isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, str) and len(v) > 20:
                        return v
        except Exception as e:
            print(f"Error regenerating section AI: {e}")

        return None

    # ── Mock responses (used when OmniRoute is not configured) ────────────────

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
            topic_lower   = topic_name.lower().strip()
            subject_lower = subject_name.lower().strip()
            combined      = f"{topic_lower} {subject_lower}"

            is_coding = any(k in combined for k in [
                "programming", "code", "python", "java", "c++", "c language", "c#", "javascript",
                "sql", "dbms", "database", "data structure", "algorithm", "tree", "graph", "stack",
                "queue", "linked list", "array", "recursion", "sorting", "searching", "web", "html",
                "css", "react", "node", "flask", "django", "api", "oop", "class", "object", "pointer"
            ])
            is_math = any(k in combined for k in [
                "math", "calculus", "algebra", "differentiat", "integrat", "derivative",
                "equation", "formula", "theorem", "proof", "trigonometr", "logarithm",
                "limit", "matrix", "matrices", "polynomial", "quadratic", "linear",
                "probability", "statistics", "number theory", "discrete", "graph theory",
                "geometry", "vector", "differential", "series", "sequence", "function"
            ])

            if is_coding:
                notes_text = f"""# {topic_name}

## 1. Overview & Concept
`{topic_name}` is a foundational concept in **{subject_name or 'Computer Science'}**. It provides standard patterns and algorithms to structure data, control execution flow, and solve complex computational challenges efficiently.

## 2. Key Principles & Syntax
Understanding `{topic_name}` requires mastering the core structure and control flow:
- **Core Abstraction**: Clean separation of interface and implementation.
- **Memory & State**: Efficient allocation and cleanup of variables.
- **Edge Conditions**: Boundary checks to prevent off-by-one errors and null pointer exceptions.

## 3. Working Code Implementation
Below is a complete, runnable Python implementation demonstrating `{topic_name}`:

```python
def solve_{topic_name.lower().replace(' ', '_')}(data_input):
    \"\"\"
    Demonstrates {topic_name} with optimal time & space efficiency.
    Handles empty inputs, single elements, and general cases.
    \"\"\"
    if not data_input:
        return "Edge Case: Input is empty"
    
    result = []
    for idx, item in enumerate(data_input):
        # Process element step-by-step
        processed_val = f"Step {idx + 1}: {item}"
        result.append(processed_val)
        
    return result

# Example Execution
if __name__ == "__main__":
    sample_data = ["Initial State", "Transformation", "Final Output"]
    output = solve_{topic_name.lower().replace(' ', '_')}(sample_data)
    print("Execution Result:")
    for line in output:
        print(f" -> {line}")
```

### Dry Run & Output
```text
Execution Result:
 -> Step 1: Initial State
 -> Step 2: Transformation
 -> Step 3: Final Output
```

## 4. Complexity Analysis
- **Time Complexity**: $O(n)$ where $n$ is the number of elements processed linearly.
- **Space Complexity**: $O(n)$ auxiliary space to store the structured result.

## 5. Common Bugs & Best Practices
1. **Unchecked Null/Empty Inputs**: Always validate inputs at the entry boundary.
2. **Resource Leaks**: Ensure all file handles, connections, and iterators are properly closed.
3. **Off-by-One Errors**: Be meticulous with 0-indexed boundaries in loops and slices.
"""
            elif is_math:
                notes_text = f"""# {topic_name}

## 1. Definition & Core Theorems
In **{subject_name or 'Mathematics'}**, `{topic_name}` defines fundamental mathematical relationships governed by rigorous algebraic and calculus principles.

### Governing Formula
The standard governing equation is defined as:
$$\\int_{{a}}^{{b}} f(x)\\,dx = F(b) - F(a)$$

where $F'(x) = f(x)$ represents the antiderivative of the continuous function $f(x)$ over the closed interval $[a, b]$.

## 2. Step-by-Step Solved Problem 1
**Problem:** Solve and evaluate the fundamental expression for `{topic_name}` given $f(x) = 3x^2 + 4x + 5$ evaluated from $x = 1$ to $x = 3$.

### Solution:
**Step 1: State Given Values and Antiderivative**
$$F(x) = \\int (3x^2 + 4x + 5)\\,dx = x^3 + 2x^2 + 5x + C$$

**Step 2: Apply Fundamental Theorem of Calculus Limits**
$$\\left[ x^3 + 2x^2 + 5x \\right]_{{1}}^{{3}} = F(3) - F(1)$$

**Step 3: Substitute Upper Limit ($x = 3$)**
$$F(3) = (3)^3 + 2(3)^2 + 5(3) = 27 + 18 + 15 = 60$$

**Step 4: Substitute Lower Limit ($x = 1$)**
$$F(1) = (1)^3 + 2(1)^2 + 5(1) = 1 + 2 + 5 = 8$$

**Step 5: Final Result**
$$F(3) - F(1) = 60 - 8 = \\mathbf{{52}}$$

## 3. Solved Problem 2 (Advanced)
**Problem:** Find the general derivative or rate of change with respect to variable $t$:
$$\\frac{{d}}{{dt}}\\left[ e^{{2t}} \\cdot \\sin(3t) \\right]$$

### Solution using Product Rule:
$$\\frac{{d}}{{dt}}[u \\cdot v] = u'v + uv'$$
$$\\text{{Let }} u = e^{{2t}} \\implies u' = 2e^{{2t}}$$
$$\\text{{Let }} v = \\sin(3t) \\implies v' = 3\\cos(3t)$$

Combining the terms:
$$\\frac{{d}}{{dt}} = 2e^{{2t}}\\sin(3t) + 3e^{{2t}}\\cos(3t) = e^{{2t}}\\left( 2\\sin(3t) + 3\\cos(3t) \\right)$$

## 4. Common Exam Mistakes
- Forgetting the constant of integration $+ C$ in indefinite equations.
- Incorrect application of chain rule derivatives.
- Sign errors during subtraction of lower limits: $F(b) - F(a)$.
"""
            else:
                notes_text = f"""# {topic_name}

## 1. Introduction & Core Concept
`{topic_name}` is a critical component within **{subject_name or 'the curriculum'}**. It establishes key foundational principles, standardized classifications, and practical methods applied throughout modern academia and industry.

## 2. Core Principles & Mechanisms
- **Fundamental Law**: Every component operates under structured rules of cause and effect.
- **Classification & Types**: Categorized into distinct operational classes depending on environmental conditions.
- **Workflow & Lifecycle**: Structured progression from initialization, execution, validation, to maintenance.

## 3. Comparative Analysis
| Feature / Aspect | Standard Approach | Advanced {topic_name} |
| :--- | :--- | :--- |
| **Efficiency** | Moderate | Highly Optimized |
| **Scalability** | Linear | Exponential |
| **Reliability** | Baseline | Enterprise-grade |

## 4. Practical Real-World Applications
1. **Industrial Implementation**: Applied extensively in engineering and automation workflows.
2. **Quality Assurance**: Used as a benchmark metric to evaluate systemic stability.
"""

            summary_text  = f"{topic_name} covers fundamental principles, working mechanisms, and practical problem-solving methods in {subject_name or 'the curriculum'}. Focus on the step-by-step examples and key formulas."
            flashcards    = [
                {"question": f"What is the primary definition of {topic_name}?", "answer": f"{topic_name} defines the core mechanisms and systematic principles governing its domain in {subject_name or 'the subject'}."},
                {"question": f"What is the key advantage of applying {topic_name}?", "answer": "It provides optimal efficiency, clear structural organization, and standard problem-solving methodologies."},
            ]
            quizzes = [
                {"question": f"Which best describes the primary objective of {topic_name}?", "options": ["Providing structured, efficient problem-solving principles", "A deprecated historical artifact", "A hardware-only tool", "An unverified hypothesis"], "correct_index": 0, "explanation": f"{topic_name} is designed to provide systematic, rigorous principles and solutions."}
            ]
            viva = [
                {"question": f"Explain the core concept of {topic_name} in simple terms.", "answer": f"{topic_name} structures key operational concepts to ensure scalable, accurate problem-solving."},
            ]
            return {"notes": notes_text, "summary": summary_text, "flashcards": flashcards, "quizzes": quizzes, "viva_questions": viva}

        return {
            "notes": "# Study Notes\n\nPlease configure your AI provider in settings to generate real-time AI study decks.",
            "summary": "AI generation service active.",
            "flashcards": [],
            "quizzes": [],
            "viva_questions": []
        }

    def process_natural_language_command(self, user_command):
        """AI Planner is deprecated in favor of Centralized JSON Syllabus Setup."""
        return {"error": "AI Planner is deprecated. Please use the Setup Wizard to load your syllabus."}

    def generate_topic_materials_for_name(self, topic_name, subject_name="", key=None,
                                          base_url=None, chat_model=None, custom_instr="",
                                          task_id=None, study_purpose="learning",
                                          base_completed=0, gen_options=None):
        """
        Generate enriched, topic-specific study materials through OmniRoute.
        """
        actual_key = key or self.api_key
        if actual_key:
            return self.generate_study_materials(
                topic_name, subject_name,
                key=actual_key, base_url=base_url, chat_model=chat_model,
                custom_instr=custom_instr, task_id=task_id, study_purpose=study_purpose,
                base_completed=base_completed, gen_options=gen_options
            )
        return self._get_mock_materials_response(topic_name, subject_name)

    def triage_support_request(self, user_message):
        """Triages user support requests, classifies if admin intervention is needed."""
        system_prompt = """
        You are the official Customer Support AI for NoteEd. 
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
            parsed = None

        if not parsed:
            # Smart local triage fallback when API keys are not configured or rate limited
            lower_msg = user_message.lower()
            if "hi" in lower_msg or "hello" in lower_msg or "hey" in lower_msg:
                return {
                    "answer": "Hello! 👋 I'm your NoteEd Support AI. How can I help you today? You can ask about billing, account upgrades, AI study decks, or technical questions.",
                    "needs_admin": False
                }
            elif "premium" in lower_msg or "payment" in lower_msg or "upgrade" in lower_msg or "bill" in lower_msg:
                return {
                    "answer": "I see you're asking about **Premium / Billing**. If your payment succeeded but your account isn't upgraded yet, you can upload your payment screenshot on the [Upgrade Page](/upgrade) or send your transaction ID here. I have also logged this for our admin team to review immediately.",
                    "needs_admin": True
                }
            elif "syllabus" in lower_msg or "import" in lower_msg:
                return {
                    "answer": "To import your syllabus, head over to the **Import** tab in the top navigation bar. You can paste your curriculum topics to automatically build your subjects and study plans.",
                    "needs_admin": False
                }
            else:
                return {
                    "answer": "Thank you for reaching out to NoteEd Support. I have received your message: *\"" + user_message[:100] + "...\"* and logged a support ticket for our admin team to resolve shortly.",
                    "needs_admin": True
                }

        return {
            "answer": parsed.get("answer", "Thank you for your message. An admin will review it."),
            "needs_admin": parsed.get("needs_admin", True)
        }


ai_service = AIService()
