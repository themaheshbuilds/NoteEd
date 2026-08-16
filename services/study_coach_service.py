import random
from datetime import datetime, timezone, timedelta

# IST Timezone (UTC + 5:30)
IST = timezone(timedelta(hours=5, minutes=30))

# ─── 24-Hour Contextual Greetings for IST ────────────────────────────────────
HOURLY_GREETINGS = {
    0: {
        "tag": "Midnight Deep Work",
        "emoji": "🌌",
        "greeting": "Burning the Midnight Oil",
        "subtitle": "Quiet hours are when complex concepts click. Stay focused and stay hydrated!"
    },
    1: {
        "tag": "Late Night Breakthrough",
        "emoji": "🌙",
        "greeting": "Late Night Deep Session",
        "subtitle": "Pushing your limits while the world sleeps. Make every minute of focus count."
    },
    2: {
        "tag": "Night Owl Mastery",
        "emoji": "🦉",
        "greeting": "Night Owl Focus Mode",
        "subtitle": "Deep revision in progress. Focus on quality retention over speed tonight."
    },
    3: {
        "tag": "Silent Hour Retention",
        "emoji": "🌠",
        "greeting": "Silent Hour Study Session",
        "subtitle": "Ultimate concentration window. Wrap up key topics and ensure proper rest."
    },
    4: {
        "tag": "Dawn Pioneer",
        "emoji": "🌅",
        "greeting": "Early Dawn Ascent",
        "subtitle": "The earliest start brings the greatest clarity. Welcome to a brand new day!"
    },
    5: {
        "tag": "Early Bird Focus",
        "emoji": "🌄",
        "greeting": "Rise & Conquer",
        "subtitle": "Fresh mind, zero distractions. Prime time for heavy numericals and theory."
    },
    6: {
        "tag": "Sunrise Ignition",
        "emoji": "☀️",
        "greeting": "Good Morning, Scholar!",
        "subtitle": "Kickstart your daily study streak before the day's rush begins."
    },
    7: {
        "tag": "Morning Momentum",
        "emoji": "🚀",
        "greeting": "Morning Acceleration",
        "subtitle": "Review your daily syllabus plan and prime your memory for the day ahead."
    },
    8: {
        "tag": "Peak Readiness",
        "emoji": "☕",
        "greeting": "Peak Morning Energy",
        "subtitle": "Your brain is at peak cognitive capacity. Tackle your most challenging subject now!"
    },
    9: {
        "tag": "Golden Study Hour",
        "emoji": "✨",
        "greeting": "Golden Focus Window",
        "subtitle": "High neural alertness detected. Optimal window for active recall and quiz drills."
    },
    10: {
        "tag": "Mid-Morning Sprint",
        "emoji": "⚡",
        "greeting": "Mid-Morning Sprint",
        "subtitle": "Keep the momentum rolling! 25 minutes of unbroken focus yields massive gains."
    },
    11: {
        "tag": "Pre-Noon Mastery",
        "emoji": "🎯",
        "greeting": "Pre-Noon Concept Lock",
        "subtitle": "Locking in key definitions, diagrams, and formulas before your midday break."
    },
    12: {
        "tag": "Midday Checkpoint",
        "emoji": "🥗",
        "greeting": "Good Afternoon!",
        "subtitle": "Take a breath, review quick flashcard decks, and recharge your mind."
    },
    13: {
        "tag": "Afternoon Reset",
        "emoji": "🌿",
        "greeting": "Post-Lunch Refresh",
        "subtitle": "Light revision, flashcards, or syllabus organizing to glide through the afternoon."
    },
    14: {
        "tag": "Power Hour",
        "emoji": "🔋",
        "greeting": "Afternoon Power Hour",
        "subtitle": "Beat the afternoon slump with active practice questions and instant AI explanations."
    },
    15: {
        "tag": "Flow State",
        "emoji": "🌊",
        "greeting": "Afternoon Flow State",
        "subtitle": "Cruising through lecture notes, formula derivations, and AI summaries."
    },
    16: {
        "tag": "Chai & Revision",
        "emoji": "☕",
        "greeting": "Tea & Revision Break",
        "subtitle": "Grab a hot cup of chai and quiz yourself on what you conquered today."
    },
    17: {
        "tag": "Twilight Productivity",
        "emoji": "🌇",
        "greeting": "Twilight Productivity",
        "subtitle": "Wrapping up daytime lecture chapters before the evening deep study session."
    },
    18: {
        "tag": "Good Evening",
        "emoji": "🌆",
        "greeting": "Good Evening, Scholar!",
        "subtitle": "Evening revision starting strong. Let's turn today's learning into permanent memory."
    },
    19: {
        "tag": "Prime Evening Retention",
        "emoji": "📚",
        "greeting": "Prime Retention Window",
        "subtitle": "Optimal time for synthesizing notes, creating cheat sheets, and active recall."
    },
    20: {
        "tag": "Nightly Consolidation",
        "emoji": "🧠",
        "greeting": "Nightly Memory Lock",
        "subtitle": "Reviewing what you studied today solidifies strong neural memory pathways."
    },
    21: {
        "tag": "Wind-Down Revision",
        "emoji": "🕯️",
        "greeting": "Evening Wind-Down",
        "subtitle": "Quick 15-minute formula recap before resting up for tomorrow's challenges."
    },
    22: {
        "tag": "Late Evening Wrap-Up",
        "emoji": "🌙",
        "greeting": "Nightly Review & Plan",
        "subtitle": "Check off completed tasks in your Planner and celebrate today's progress!"
    },
    23: {
        "tag": "Midnight Prep",
        "emoji": "🌌",
        "greeting": "Final Review of the Day",
        "subtitle": "Finishing final problem sets. Remember: high-quality sleep cements long-term memory."
    }
}

# ─── 20+ Proven Cognitive & Pedagogical Study Techniques ─────────────────────
STUDY_COACH_TIPS_POOL = [
    {
        "id": "feynman",
        "title": "The Feynman Technique",
        "emoji": "💡",
        "category": "Deep Understanding",
        "tip": "Explain the concept out loud in plain 5th-grade words without technical jargon. Wherever you hesitate, re-study that exact gap."
    },
    {
        "id": "blurting",
        "title": "The Blurting Method",
        "emoji": "✍️",
        "category": "Active Recall",
        "tip": "Read a topic for 15 minutes, close your notes completely, and write down everything you remember. Fill in gaps in a different color pen."
    },
    {
        "id": "interleaving",
        "title": "Interleaved Practice",
        "emoji": "🔀",
        "category": "Retention Boost",
        "tip": "Mix 2-3 different topics in one study block instead of doing 4 hours of just one topic. Interleaving boosts exam problem recognition by 43%."
    },
    {
        "id": "spaced_repetition",
        "title": "Spaced Retrieval Intervals",
        "emoji": "⏳",
        "category": "Memory Decay Prevention",
        "tip": "Review new notes on Day 1, Day 3, and Day 7. This flattens the Ebbinghaus forgetting curve and cements knowledge into long-term storage."
    },
    {
        "id": "dual_coding",
        "title": "Dual Coding Strategy",
        "emoji": "🎨",
        "category": "Cognitive Processing",
        "tip": "Pair complex mathematical formulas or chemical pathways with a visual sketch or flowchart. Encoding visually and verbally doubles recall paths."
    },
    {
        "id": "pomodoro",
        "title": "25/5 Pomodoro Intervals",
        "emoji": "🍅",
        "category": "Focus & Stamina",
        "tip": "25 minutes of single-task immersion followed by 5 minutes of physical movement keeps your prefrontal cortex energized without burnout."
    },
    {
        "id": "sleep_consolidation",
        "title": "Sleep Memory Replay",
        "emoji": "🛌",
        "category": "Neuroscience",
        "tip": "Review your most difficult theorem 20 minutes before sleep. During deep NREM sleep, your hippocampus replays and hardwires the neural trace."
    },
    {
        "id": "question_first",
        "title": "Question-First Inversion",
        "emoji": "❓",
        "category": "Prime Attention",
        "tip": "Attempt 3 practice questions BEFORE reading the chapter. It primes your brain's reticular activating system to hunt for relevant answers."
    },
    {
        "id": "sq3r",
        "title": "The SQ3R Framework",
        "emoji": "📖",
        "category": "Reading Efficiency",
        "tip": "Survey headings, Question what you must learn, Read actively, Recite key points from memory, and Review all summaries."
    },
    {
        "id": "derivation_drill",
        "title": "Derivation Over Memorization",
        "emoji": "📐",
        "category": "STEM Mastery",
        "tip": "Never just memorize a final formula. Derive it from first principles once, and you'll easily reconstruct it even under heavy exam stress."
    },
    {
        "id": "chunking",
        "title": "Cognitive Chunking",
        "emoji": "🧩",
        "category": "Working Memory",
        "tip": "Break massive 60-page chapters into 4 digestible sub-themes. Mastering small milestones triggers dopamine and maintains high study velocity."
    },
    {
        "id": "mind_dump",
        "title": "Pre-Exam Brain Dump",
        "emoji": "⚡",
        "category": "Exam Strategy",
        "tip": "The moment your exam begins, immediately write down the 5 formulas you fear forgetting in the margin of your scratch paper."
    },
    {
        "id": "active_recall",
        "title": "Closed-Book Self-Testing",
        "emoji": "🎯",
        "category": "Testing Effect",
        "tip": "Re-reading notes creates an illusion of competence. Only retrieval practice (forcing your brain to generate answers) creates true mastery."
    },
    {
        "id": "rubber_duck",
        "title": "The Rubber Duck Method",
        "emoji": "🦆",
        "category": "Problem Solving",
        "tip": "When stuck on a derivation or code logic, explain the problem step-by-step to an inanimate object or your AI tutor to spot logical flaws."
    },
    {
        "id": "hydration_focus",
        "title": "Hydration & Neural Velocity",
        "emoji": "💧",
        "category": "Physical Energy",
        "tip": "A mere 2% drop in hydration reduces cognitive speed and short-term memory by up to 15%. Keep water near your desk at all times."
    }
]


def get_ist_time_info():
    """Get current Indian Standard Time (IST) info, formatted in 12-hour time."""
    now_ist = datetime.now(IST)
    hour = now_ist.hour
    
    greeting_info = HOURLY_GREETINGS.get(hour, HOURLY_GREETINGS[12])
    
    time_12h = now_ist.strftime("%I:%M %p").lstrip("0") # e.g. "6:08 PM"
    time_12h_full = now_ist.strftime("%I:%M:%S %p")
    date_str = now_ist.strftime("%A, %d %b %Y") # e.g. "Sunday, 16 Aug 2026"
    date_short = now_ist.strftime("%d %b %Y")
    
    return {
        "datetime": now_ist,
        "hour": hour,
        "time_12h": time_12h,
        "time_12h_full": time_12h_full,
        "date_str": date_str,
        "date_short": date_short,
        "timezone_label": "IST (UTC+5:30)",
        "tag": greeting_info["tag"],
        "emoji": greeting_info["emoji"],
        "greeting": greeting_info["greeting"],
        "subtitle": greeting_info["subtitle"]
    }


def get_daily_study_tips(count=2):
    """Get dynamic rotating study tips that change deterministically per day of the year."""
    now_ist = datetime.now(IST)
    day_seed = now_ist.year * 1000 + now_ist.timetuple().tm_yday
    
    rng = random.Random(day_seed)
    selected = rng.sample(STUDY_COACH_TIPS_POOL, min(count, len(STUDY_COACH_TIPS_POOL)))
    return selected


def get_all_study_tips():
    """Get the full pool of study tips for dynamic client-side exploration."""
    return STUDY_COACH_TIPS_POOL
