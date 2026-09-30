"""Local page that uploads a reference and a teacher exam, then calls the existing pipeline."""

from __future__ import annotations

import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from flask import Flask, redirect, render_template, request, send_file, url_for

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from format.format_integrity import check_format
from format.nonconformance import find_nonconformances, write_nonconformance_file
from format.word_formatter import format_exam
from run_core import run_pipeline


def create_app(data_root: Path | None = None) -> Flask:
    app = Flask(__name__)
    root = Path(data_root) if data_root else ROOT / "data"
    app.config["DATA_ROOT"] = root

    def references_dir() -> Path:
        path = root / "references"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def exams_dir() -> Path:
        path = root / "exams"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def reference_path() -> Path:
        return references_dir() / "active.docx"

    def reference_meta_path() -> Path:
        return references_dir() / "active.json"

    def index_path() -> Path:
        return exams_dir() / "index.json"

    def load_index() -> list[dict]:
        path = index_path()
        if not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8"))

    def save_index(rows: list[dict]) -> None:
        index_path().write_text(json.dumps(rows, indent=2), encoding="utf-8")

    def active_reference_name() -> str | None:
        meta = reference_meta_path()
        if not reference_path().exists() or not meta.exists():
            return None
        return json.loads(meta.read_text(encoding="utf-8")).get("original_filename")

    def is_docx(filename: str) -> bool:
        return bool(filename) and filename.lower().endswith(".docx")

    def download_stem(filename: str) -> str:
        stem = Path(filename).stem
        cleaned = re.sub(r"[^\w .\-]", "", stem).strip()
        return cleaned or "exam"

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            reference=active_reference_name(),
            exams=list(reversed(load_index())),
            message=request.args.get("message", ""),
            error=request.args.get("error", ""),
            download_id=request.args.get("download", ""),
        )

    @app.post("/reference")
    def upload_reference():
        upload = request.files.get("reference")
        if upload is None or not is_docx(upload.filename or ""):
            return redirect(url_for("index", error="Upload a DOCX reference exam."))
        target = reference_path()
        temporary = target.with_suffix(".docx.tmp")
        upload.save(temporary)
        temporary.replace(target)
        reference_meta_path().write_text(
            json.dumps({"original_filename": Path(upload.filename).name}, indent=2),
            encoding="utf-8",
        )
        return redirect(url_for("index", message="Reference exam saved."))

    @app.post("/reference/delete")
    def delete_reference():
        reference_path().unlink(missing_ok=True)
        reference_meta_path().unlink(missing_ok=True)
        return redirect(url_for("index", message="Reference exam removed."))

    @app.post("/format")
    def format_teacher():
        if active_reference_name() is None:
            return redirect(url_for("index", error="No Reference Exam loaded."))
        upload = request.files.get("teacher")
        if upload is None or not is_docx(upload.filename or ""):
            return redirect(url_for("index", error="Upload a DOCX teacher exam."))
        original_name = Path(upload.filename).name
        exam_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:6]
        folder = exams_dir() / exam_id
        folder.mkdir(parents=True)
        original = folder / "original.docx"
        formatted = folder / "formatted.docx"
        upload.save(original)
        try:
            errors = find_nonconformances(original, reference_path())
            if errors:
                write_nonconformance_file(original, formatted, errors)
                formatted_name = download_stem(original_name) + "_CORRECTIONS.docx"
                message = (
                    "This exam does not match the Reference Exam. "
                    "Download the file, follow the yellow notes, delete those notes, and upload again."
                )
            else:
                result = run_pipeline(original, reference_path(), folder / "work")
                if not result["ok"]:
                    shutil.rmtree(folder, ignore_errors=True)
                    return redirect(url_for("index", error="Formatting failed. The exam was not saved."))
                format_exam(result["blocks"], original, formatted)
                problems = check_format(result["blocks"], original, formatted, reference_path())
                if problems:
                    shutil.rmtree(folder, ignore_errors=True)
                    return redirect(url_for("index", error="Formatting failed. The exam was not saved."))
                formatted_name = download_stem(original_name) + "_FORMATTED.docx"
                message = "Exam formatted."
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            return redirect(url_for("index", error="Formatting failed. The exam was not saved."))
        rows = load_index()
        rows.append(
            {
                "id": exam_id,
                "original_filename": original_name,
                "formatted_filename": formatted_name,
                "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
        )
        save_index(rows)
        return redirect(url_for("index", message=message, download=exam_id))

    @app.get("/exams/<exam_id>/download")
    def download_exam(exam_id: str):
        row = next((item for item in load_index() if item["id"] == exam_id), None)
        path = exams_dir() / exam_id / "formatted.docx"
        if row is None or not path.exists():
            return redirect(url_for("index", error="That formatted exam is not available."))
        return send_file(path, as_attachment=True, download_name=row["formatted_filename"])

    @app.post("/exams/<exam_id>/delete")
    def delete_exam(exam_id: str):
        rows = [item for item in load_index() if item["id"] != exam_id]
        save_index(rows)
        shutil.rmtree(exams_dir() / exam_id, ignore_errors=True)
        return redirect(url_for("index", message="Formatted exam removed."))

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
