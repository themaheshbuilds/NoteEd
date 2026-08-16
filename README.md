<div align="center">

# ⚡ NoteEd — AI Study Partner
### *AI-Driven University Study Companion & Academic Exam Engine*

<a href="https://git.io/typing-svg">
  <img src="https://readme-typing-svg.demolab.com?font=Fira+Code&weight=600&size=22&pause=1000&color=3B82F6&center=true&vcenter=true&width=680&lines=AI-Powered+University+Syllabus+%26+Exam+Engine;Comprehensive+Textbook+Notes+%26+Solved+Math+Problems;Active+Recall+Flashcards%2C+MCQ+Quizzes+%26+Viva+Voce;Context-Aware+AI+Tutor+Chat+%26+Offline+PWA" alt="Typing Banner" />
</a>

<br/><br/>

[![GitHub Repo](https://img.shields.io/badge/GitHub-NoteEd-181717?style=for-the-badge&logo=github)](https://github.com/themaheshbuilds/NoteEd)
[![Python Version](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Framework](https://img.shields.io/badge/Flask-2.x-000000?style=for-the-badge&logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![Database](https://img.shields.io/badge/Supabase-PostgreSQL-3ECF8E?style=for-the-badge&logo=supabase&logoColor=white)](https://supabase.com)
[![PWA Ready](https://img.shields.io/badge/PWA-Installable-5A0FC8?style=for-the-badge&logo=pwa&logoColor=white)](#)

---

</div>

## 📖 About NoteEd

**NoteEd** is a full-stack, AI-powered academic study platform engineered for university students across **Engineering (B.Tech), Management (MBA), Commerce (B.Com), and General Degree programs**. 

Instead of generating superficial summaries, NoteEd structures every subject into an exhaustive **5-Unit academic syllabus** with **step-by-step solved numerical calculations**, **spaced repetition flashcards**, **timed MCQ practice exams**, **Viva Voce oral interview decks**, and a **context-aware AI Tutor Chat**.

- 🎓 **Universal Curriculum**: Pre-configured standard syllabus branches + automated 5-unit custom degree curriculum generator.
- 📐 **Solved Mathematics Engine**: 75%+ numerical problem-solving weighting with complete LaTeX arithmetic derivations.
- ⚡ **Multi-Modal Active Recall**: Flashcards, timed MCQ quizzes with explanations, and viva interview preparation.
- 📱 **Native PWA Experience**: Installable on Android, iOS, Windows, and Mac with offline capabilities and smooth responsive UI.

> [!TIP]
> ### ⚡ Educational Philosophy
> *"True conceptual mastery comes from step-by-step worked practice, active recall, and instant feedback."*

---

## 📌 Core Features

- 📚 **Automated 5-Unit Syllabus Builder**: Select standard branches or specify custom degrees (MBA, Degree, etc.) with automated unit structuring.
- 📝 **Exhaustive Textbook Notes**: Long-form academic chapters featuring definitions, architecture, real-world applications, and cheat sheets.
- 🧮 **Step-by-Step Solved Math Problems**: 6+ fully worked numerical practice problems per topic (Given Data $\rightarrow$ Formula $\rightarrow$ Substitution $\rightarrow$ Step-by-Step Derivation $\rightarrow$ Boxed Final Answer).
- ⚡ **Spaced Repetition Flashcards**: Interactive confidence rating (Easy, Medium, Hard) to optimize active recall.
- 🎯 **Timed MCQ Quizzes & Analytics**: Exam-level multiple-choice tests with detailed explanations and real-time accuracy scoring.
- 🎙️ **Viva Voce & Technical Oral Exams**: Master tricky interview questions, edge cases, and oral examination concepts.
- 💬 **Embedded AI Tutor Chat**: Floating, expandable AI assistant with free-scrolling typewriter streaming and document Q&A.
- 🛑 **Live Generation Control**: Progressive generation pipeline with real-time exact digital countdown timer and *"Stop & Show Generated Content"* button.

---

## 🛠️ Technology Stack

<div align="center">

### **Backend & AI Gateway**
![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-000000?style=for-the-badge&logo=flask&logoColor=white)
![Groq](https://img.shields.io/badge/Groq_Cloud-F05A28?style=for-the-badge&logo=fastapi&logoColor=white)
![Google Gemini](https://img.shields.io/badge/Google_Gemini-4285F4?style=for-the-badge&logo=google&logoColor=white)
![OpenRouter](https://img.shields.io/badge/OpenRouter-6366F1?style=for-the-badge&logo=openai&logoColor=white)

### **Frontend & UI Systems**
![JavaScript](https://img.shields.io/badge/JavaScript-F7DF1E?style=for-the-badge&logo=javascript&logoColor=black)
![HTML5](https://img.shields.io/badge/HTML5-E34F26?style=for-the-badge&logo=html5&logoColor=white)
![CSS3](https://img.shields.io/badge/CSS3-1572B6?style=for-the-badge&logo=css3&logoColor=white)
![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-06B6D4?style=for-the-badge&logo=tailwindcss&logoColor=white)
![MathJax 3](https://img.shields.io/badge/MathJax_LaTeX-2E7D32?style=for-the-badge&logo=latex&logoColor=white)

### **Databases & Cloud Architecture**
![Supabase](https://img.shields.io/badge/Supabase-3ECF8E?style=for-the-badge&logo=supabase&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-316192?style=for-the-badge&logo=postgresql&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-003B57?style=for-the-badge&logo=sqlite&logoColor=white)
![Vercel](https://img.shields.io/badge/Vercel-000000?style=for-the-badge&logo=vercel&logoColor=white)
![PWA](https://img.shields.io/badge/PWA_Service_Worker-5A0FC8?style=for-the-badge&logo=pwa&logoColor=white)

</div>

---

## 🚀 Application Architecture

<div align="center">

| Module | Description | Location |
| :--- | :--- | :--- |
| 🎓 **Syllabus & Curriculum Engine** | Preloaded academic datasets + custom degree auto-generators | [`data/syllabus/`](file:///c:/Users/vilas/Desktop/My%20Projects/NoteEd/data/syllabus) |
| 🤖 **Multi-Provider AI Gateway** | Failover rotation across Groq, Gemini, and OpenRouter | [`services/ai_service.py`](file:///c:/Users/vilas/Desktop/My%20Projects/NoteEd/services/ai_service.py) |
| ⚙️ **Background Task Engine** | Multi-step asynchronous generation with live progress | [`services/task_service.py`](file:///c:/Users/vilas/Desktop/My%20Projects/NoteEd/services/task_service.py) |
| 🗄️ **Hybrid Database Layer** | Supabase Postgres with local SQLite automatic fallback | [`services/db_service.py`](file:///c:/Users/vilas/Desktop/My%20Projects/NoteEd/services/db_service.py) |
| 📱 **Progressive Web App (PWA)** | Service Worker v7, install triggers, and offline caching | [`static/sw.js`](file:///c:/Users/vilas/Desktop/My%20Projects/NoteEd/static/sw.js) |
| 🎨 **Kiraak Design System** | Modern dark/light UI, MathJax without horizontal scrolls | [`templates/`](file:///c:/Users/vilas/Desktop/My%20Projects/NoteEd/templates) |

</div>

---

## ⚡ Quickstart & Local Setup

### 1. Clone the Repository
```bash
git clone https://github.com/themaheshbuilds/NoteEd.git
cd NoteEd
```

### 2. Create Virtual Environment & Install Dependencies
```bash
python -m venv venv
# Windows
venv\Scripts\activate
# Linux / Mac
source venv/bin/activate

pip install -r requirements.txt
```

### 3. Configure Environment Variables
Create a `.env` file in the root directory:
```ini
SECRET_KEY=your-secret-key-here
GROQ_API_KEY=gsk_...
GEMINI_API_KEY=AIzaSy...
OPENROUTER_API_KEY=sk-or-v1-...
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-supabase-key
```

### 4. Run Development Server
```bash
python app.py
```
Open **`http://127.0.0.1:5000`** in your browser.

---

<div align="center">

### 📬 Connect & Author
*Built with ❤️ by **Mahesh Vilasagaram***

[![LinkedIn](https://img.shields.io/badge/LinkedIn-Connect-0A66C2?style=for-the-badge&logo=linkedin)](https://www.linkedin.com/in/mahesh-vilasagaram)
[![Email](https://img.shields.io/badge/Email-Contact_Author-EA4335?style=for-the-badge&logo=gmail&logoColor=white)](mailto:vilasagarammahesh90@gmail.com)
[![GitHub](https://img.shields.io/badge/GitHub-themaheshbuilds-181717?style=for-the-badge&logo=github)](https://github.com/themaheshbuilds)

<br/>

<sub>© 2026 **NoteEd** • Empowering University Students with AI</sub>

</div>
