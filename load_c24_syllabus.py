import sys
import os
import json
import uuid

# Add the project directory to path so we can import services
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.db_service import db_service

def add_syllabus():
    user_id = '363c3b41-02a9-46b1-8a7f-bb95ec4959ae'
    
    syllabus_json = {
        "year": "Diploma I Semester",
        "group": "AI & ML",
        "subjects": [
            {
                "subject": "Basic English",
                "code": "HU-101",
                "chapters": [
                    {
                        "name": "Vocabulary Through Reading - I",
                        "topics": [
                            "How to Learn a New Word",
                            "Synonyms, Antonyms and One-Word Substitutes",
                            "Purpose of Reading",
                            "Types of Reading",
                            "Types of Paragraphs and Questions"
                        ]
                    },
                    {
                        "name": "Speaking - I",
                        "topics": [
                            "Need for English",
                            "Classroom English",
                            "Expressing Likes and Dislikes",
                            "Expressing Feelings"
                        ]
                    },
                    {
                        "name": "Grammar - I",
                        "topics": [
                            "Basic Sentence Structures",
                            "Tenses-I",
                            "Tenses-II",
                            "Voice"
                        ]
                    },
                    {
                        "name": "Speaking - II",
                        "topics": [
                            "Introducing Oneself",
                            "Talking about daily routine",
                            "Fixing, Cancelling and Rescheduling Appointments",
                            "Extending, Accepting and Declining Invitations"
                        ]
                    },
                    {
                        "name": "Grammar - II",
                        "topics": [
                            "Adjectives",
                            "Prepositions",
                            "Asking Questions -I",
                            "Asking Questions - II"
                        ]
                    },
                    {
                        "name": "Writing-I",
                        "topics": [
                            "Paragraph Writing - I",
                            "Paragraph Writing - II",
                            "Letter Writing - I",
                            "Letter Writing - II"
                        ]
                    }
                ]
            },
            {
                "subject": "Basic Engineering Mathematics",
                "code": "SC-102",
                "chapters": [
                    {
                        "name": "Algebra",
                        "topics": [
                            "Logarithms",
                            "Partial Fractions"
                        ]
                    },
                    {
                        "name": "Matrices and Determinants",
                        "topics": [
                            "Matrices",
                            "Determinants"
                        ]
                    },
                    {
                        "name": "Trigonometry - I",
                        "topics": [
                            "Trigonometric Ratios of Allied Angles",
                            "Compound Angles"
                        ]
                    },
                    {
                        "name": "Trigonometry - II",
                        "topics": [
                            "Multiple and sub-multiple angles",
                            "Transformations"
                        ]
                    },
                    {
                        "name": "Trigonometry - III",
                        "topics": [
                            "Inverse Trigonometric Functions",
                            "Properties of Triangles"
                        ]
                    },
                    {
                        "name": "Applications of Trigonometry and Matrices",
                        "topics": [
                            "Solutions of Triangles",
                            "Solutions of system of Simultaneous Linear Equations"
                        ]
                    }
                ]
            },
            {
                "subject": "Basic Physics",
                "code": "SC-103",
                "chapters": [
                    {
                        "name": "Units, Dimensions and Measurements",
                        "topics": [
                            "Physical quantity",
                            "Fundamental and derived quantities",
                            "Dimensions and dimensional formula",
                            "Principle of homogeneity",
                            "Applications and limitations of dimensional analysis",
                            "Errors in measurement"
                        ]
                    },
                    {
                        "name": "Vectors",
                        "topics": [
                            "Scalar and Vector quantities",
                            "Triangle and Parallelogram law of vectors",
                            "Scalar product of vectors",
                            "Vector product of vectors"
                        ]
                    },
                    {
                        "name": "Mechanics",
                        "topics": [
                            "Equations of motion",
                            "Projectile motion",
                            "Friction (types, laws, advantages and disadvantages)"
                        ]
                    },
                    {
                        "name": "Properties of Matter",
                        "topics": [
                            "Elasticity (Stress, Strain, Hooke's Law)",
                            "Surface tension",
                            "Viscosity"
                        ]
                    },
                    {
                        "name": "Work and Energy",
                        "topics": [
                            "Work, Power and Energy",
                            "Work-Energy theorem",
                            "Law of conservation of energy",
                            "Renewable and Non-renewable energy sources"
                        ]
                    },
                    {
                        "name": "Thermal Physics",
                        "topics": [
                            "Thermal expansion",
                            "Thermal conductivity",
                            "Boyle's law and Charles' laws",
                            "Ideal gas equation",
                            "Laws of thermodynamics"
                        ]
                    }
                ]
            },
            {
                "subject": "General Engineering Chemistry",
                "code": "SC-104",
                "chapters": [
                    {
                        "name": "Fundamentals of Chemistry",
                        "topics": [
                            "Atomic Structure",
                            "Chemical Bonding",
                            "Oxidation-Reduction"
                        ]
                    },
                    {
                        "name": "Solutions and Colloids",
                        "topics": [
                            "Mole concept",
                            "Molarity and Normality",
                            "Colloids and industrial applications"
                        ]
                    },
                    {
                        "name": "Acids and Bases",
                        "topics": [
                            "Theories of acids and bases",
                            "Ionic product of water",
                            "pH",
                            "Buffer solutions",
                            "Indicators"
                        ]
                    },
                    {
                        "name": "Environmental Science",
                        "topics": [
                            "Ecosystem",
                            "Biodiversity",
                            "Green Chemistry",
                            "e-waste Management"
                        ]
                    },
                    {
                        "name": "Water Technology",
                        "topics": [
                            "Hardness of water",
                            "Softening methods",
                            "Municipal treatment",
                            "Reverse Osmosis",
                            "Desalination"
                        ]
                    },
                    {
                        "name": "Electrochemistry",
                        "topics": [
                            "Conductors and electrolytes",
                            "Electrolysis",
                            "Faraday's laws",
                            "Electrolytic refining"
                        ]
                    }
                ]
            },
            {
                "subject": "Computer Fundamentals & Hardware",
                "code": "CS-105",
                "chapters": [
                    {
                        "name": "Fundamentals of Digital Computer",
                        "topics": [
                            "Generations of Computers",
                            "Block diagram",
                            "CPU functional parameters",
                            "Memory types"
                        ]
                    },
                    {
                        "name": "DOS Operating Systems",
                        "topics": [
                            "Need for OS",
                            "DOS Commands",
                            "Directories and files"
                        ]
                    },
                    {
                        "name": "Windows Operating Systems",
                        "topics": [
                            "Features of Windows",
                            "File and folder management",
                            "Control panel utilities"
                        ]
                    },
                    {
                        "name": "PC hardware and its Components",
                        "topics": [
                            "BIOS",
                            "Motherboard components",
                            "I/O ports",
                            "SMPS"
                        ]
                    },
                    {
                        "name": "Processors, Memories",
                        "topics": [
                            "Processors (INTEL/AMD)",
                            "Chipsets",
                            "RAM types and upgradation"
                        ]
                    },
                    {
                        "name": "Mass storage devices & I/O Devices",
                        "topics": [
                            "Hard Disk drive",
                            "Optical disk drives",
                            "SSD",
                            "Input/Output devices"
                        ]
                    }
                ]
            }
        ]
    }

    # 1. Check if the semester already exists or create a new one
    semester_name = f"TG SBTET C24 Curriculum - {syllabus_json['year']} - {syllabus_json['group']}"
    existing_sem = db_service.query("SELECT id FROM semesters WHERE user_id = ? AND name = ?", (user_id, semester_name), one=True)
    
    if existing_sem:
        semester_id = existing_sem["id"]
        print(f"Using existing semester: {semester_name}")
    else:
        semester_id = str(uuid.uuid4())
        db_service.execute("INSERT INTO semesters (id, user_id, name) VALUES (?, ?, ?)", (semester_id, user_id, semester_name))
        print(f"Created semester: {semester_name}")

    # Set as current semester
    db_service.execute("UPDATE profiles SET current_semester_id = ? WHERE id = ?", (semester_id, user_id))

    # 2. Add subjects
    for subj in syllabus_json['subjects']:
        subj_name = subj['subject']
        subj_code = subj.get('code', '')
        
        # Check if subject exists
        existing_subject = db_service.query("SELECT id FROM subjects WHERE semester_id = ? AND name = ?", (semester_id, subj_name), one=True)
        if existing_subject:
            subject_id = existing_subject["id"]
            print(f"  Subject already exists: {subj_name}")
        else:
            subject_id = str(uuid.uuid4())
            db_service.execute("INSERT INTO subjects (id, semester_id, name, code) VALUES (?, ?, ?, ?)", 
                               (subject_id, semester_id, subj_name, subj_code))
            print(f"  Added subject: {subj_name}")

        # 3. Add chapters (units)
        for u_idx, chapter in enumerate(subj.get('chapters', [])):
            unit_name = chapter['name']
            
            # Check if unit exists
            existing_unit = db_service.query("SELECT id FROM units WHERE subject_id = ? AND name = ?", (subject_id, unit_name), one=True)
            if existing_unit:
                unit_id = existing_unit["id"]
                print(f"    Unit already exists: {unit_name}")
            else:
                unit_id = str(uuid.uuid4())
                db_service.execute("INSERT INTO units (id, subject_id, name, number) VALUES (?, ?, ?, ?)", 
                                   (unit_id, subject_id, unit_name, u_idx + 1))
                print(f"    Added unit: {unit_name}")

            # 4. Add topics
            for t_idx, topic_name in enumerate(chapter.get('topics', [])):
                existing_topic = db_service.query("SELECT id FROM topics WHERE unit_id = ? AND name = ?", (unit_id, topic_name), one=True)
                if existing_topic:
                    print(f"      Topic already exists: {topic_name}")
                else:
                    topic_id = str(uuid.uuid4())
                    db_service.execute("INSERT INTO topics (id, unit_id, name, order_index) VALUES (?, ?, ?, ?)", 
                                       (topic_id, unit_id, topic_name, t_idx + 1))
                    print(f"      Added topic: {topic_name}")

if __name__ == '__main__':
    add_syllabus()
    print("Syllabus added successfully.")

