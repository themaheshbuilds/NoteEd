import os
import uuid
import json
from flask import Blueprint, request, redirect, url_for, flash, jsonify, send_from_directory, current_app
from werkzeug.utils import secure_filename
from services.db_service import db_service
from services.image_service import ImageService
from services.pdf_service import PDFService
from services.ai_service import ai_service

files_bp = Blueprint("files", __name__)

ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "docx", "pptx", "txt"}

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

@files_bp.route("/upload/<topic_id>", methods=["POST"])
def upload_file(topic_id):
    if "file" not in request.files:
        flash("No file part", "error")
        return redirect(url_for("dashboard.view_topic", topic_id=topic_id))
        
    file = request.files["file"]
    if file.filename == "":
        flash("No selected file", "error")
        return redirect(url_for("dashboard.view_topic", topic_id=topic_id))
        
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_ext = filename.rsplit(".", 1)[1].lower()
        
        # Ensure uploads folder exists
        uploads_dir = os.path.join(current_app.root_path, "uploads")
        os.makedirs(uploads_dir, exist_ok=True)
        
        unique_filename = f"{uuid.uuid4()}.{file_ext}"
        file_path = os.path.join(uploads_dir, unique_filename)
        
        # Read file bytes for processing
        file_bytes = file.read()
        
        # Core Document Enhancement / Processing
        processed_bytes = file_bytes
        if file_ext in ["jpg", "jpeg", "png"]:
            # Auto-rotate, resize, compress, and enhance contrast/sharpness via Pillow
            processed_bytes = ImageService.enhance_image(file_bytes)
            with open(file_path, "wb") as f:
                f.write(processed_bytes)
        else:
            with open(file_path, "wb") as f:
                f.write(file_bytes)
                
        # Save to database
        file_id = str(uuid.uuid4())
        db_service.execute(
            """INSERT INTO files (id, topic_id, name, file_path, file_type, file_size, is_favorite, is_archived) 
               VALUES (?, ?, ?, ?, ?, ?, 0, 0)""",
            (file_id, topic_id, filename, unique_filename, file_ext, len(processed_bytes))
        )
        
        # AI Vision processing (OCR & document understanding) in the background / synchronously here
        # If it's a PDF, we extract page 1 (or more) as images, then send to NIM Vision AI.
        # If it's an image, we send the enhanced image directly.
        try:
            vision_result = None
            if file_ext in ["jpg", "jpeg", "png"]:
                vision_result = ai_service.process_vision_document(processed_bytes)
            elif file_ext == "pdf":
                pages = PDFService.extract_pages_as_images(processed_bytes, max_pages=1)
                if pages:
                    # Send first page image to NIM Vision
                    vision_result = ai_service.process_vision_document(pages[0][1])
            
            if vision_result:
                # Update file in DB with AI extracted insights
                db_service.execute(
                    """UPDATE files SET 
                       ocr_text = ?, 
                       summary = ?, 
                       keywords = ?,
                       tags = ?
                       WHERE id = ?""",
                    (
                        vision_result.get("full_text", ""),
                        vision_result.get("summary", ""),
                        ",".join(vision_result.get("keywords", [])),
                        ",".join(vision_result.get("topics", [])),
                        file_id
                    )
                )
                
                # Optionally, auto-generate notes/flashcards if requested
                if vision_result.get("full_text"):
                    # Add as an AI generated note
                    note_id = str(uuid.uuid4())
                    db_service.execute(
                        """INSERT INTO notes (id, topic_id, title, content, is_ai_generated) 
                           VALUES (?, ?, ?, ?, 1)""",
                        (note_id, topic_id, f"AI Summary: {vision_result.get('title', filename)}", vision_result.get("summary", ""),)
                    )
        except Exception as e:
            print(f"Error during AI vision processing: {e}")
            
        flash("File uploaded and processed successfully with AI Vision.", "success")
    else:
        flash("Unsupported file type.", "error")
        
    return redirect(url_for("dashboard.view_topic", topic_id=topic_id))

@files_bp.route("/download/<file_id>")
def download_file(file_id):
    file_record = db_service.query("SELECT * FROM files WHERE id = ?", (file_id,), one=True)
    if not file_record:
        flash("File not found.", "error")
        return redirect(url_for("dashboard.index"))
        
    uploads_dir = os.path.join(current_app.root_path, "uploads")
    return send_from_directory(uploads_dir, file_record["file_path"], as_attachment=True, download_name=file_record["name"])

@files_bp.route("/file/<file_id>/favorite", methods=["POST"])
def toggle_favorite(file_id):
    file_record = db_service.query("SELECT * FROM files WHERE id = ?", (file_id,), one=True)
    if file_record:
        new_fav = 0 if file_record["is_favorite"] else 1
        db_service.execute("UPDATE files SET is_favorite = ? WHERE id = ?", (new_fav, file_id))
        return jsonify({"success": True, "is_favorite": bool(new_fav)})
    return jsonify({"error": "File not found"}), 404

@files_bp.route("/file/<file_id>/delete", methods=["POST"])
def delete_file(file_id):
    file_record = db_service.query("SELECT * FROM files WHERE id = ?", (file_id,), one=True)
    if file_record:
        topic_id = file_record["topic_id"]
        # Delete file from disk
        uploads_dir = os.path.join(current_app.root_path, "uploads")
        try:
            os.remove(os.path.join(uploads_dir, file_record["file_path"]))
        except OSError:
            pass
        db_service.execute("DELETE FROM files WHERE id = ?", (file_id,))
        flash("File deleted.", "success")
        return redirect(url_for("dashboard.view_topic", topic_id=topic_id))
    return redirect(url_for("dashboard.index"))

