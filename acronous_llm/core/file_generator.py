import io
import csv
import json
import base64


class FileGenerator:
    def __init__(self, config, llm=None):
        self.config = config
        self._llm = llm

    def generate(self, content, file_type, filename=None):
        if file_type == "csv":
            return self._generate_csv(content, filename)
        elif file_type == "pdf":
            return self._generate_pdf(content, filename)
        elif file_type == "svg":
            return self._generate_svg(content, filename)
        elif file_type == "json":
            return self._generate_json(content, filename)
        elif file_type == "html":
            return self._generate_html(content, filename)
        elif file_type == "md":
            return self._generate_text(content, filename, "md")
        else:
            return self._generate_text(content, filename, "txt")

    def _generate_csv(self, content, filename=None):
        try:
            output = io.StringIO()
            lines = [l.strip() for l in content.strip().split("\n") if l.strip()]
            writer = csv.writer(output)
            for line in lines:
                writer.writerow(line.split(","))
            raw = output.getvalue().encode("utf-8")
            name = filename or "data.csv"
            return {"file_data": base64.b64encode(raw).decode(), "file_name": name, "file_type": "csv", "mime": "text/csv"}
        except Exception:
            raw = content.encode("utf-8")
            return {"file_data": base64.b64encode(raw).decode(), "file_name": filename or "data.csv", "file_type": "csv", "mime": "text/csv"}

    def _generate_pdf(self, content, filename=None):
        try:
            from fpdf import FPDF
            pdf = FPDF()
            pdf.add_page()
            pdf.add_font("DejaVu", "", r"C:\Windows\Fonts\DejaVuSans.ttf", uni=True)
            pdf.set_font("DejaVu", size=11)
            for line in content.split("\n"):
                line = line.strip()
                if not line:
                    pdf.ln(4)
                    continue
                try:
                    pdf.multi_cell(0, 6, line)
                except Exception:
                    line_clean = line.encode("latin-1", "replace").decode("latin-1")
                    pdf.multi_cell(0, 6, line_clean)
            raw = pdf.output(dest="S").encode("latin-1")
            name = filename or "document.pdf"
            return {"file_data": base64.b64encode(raw).decode(), "file_name": name, "file_type": "pdf", "mime": "application/pdf"}
        except ImportError:
            raw = content.encode("utf-8")
            return {"file_data": base64.b64encode(raw).decode(), "file_name": filename or "document.pdf", "file_type": "pdf", "mime": "application/pdf"}
        except Exception:
            raw = content.encode("utf-8")
            return {"file_data": base64.b64encode(raw).decode(), "file_name": filename or "document.pdf", "file_type": "pdf", "mime": "application/pdf"}

    def _generate_svg(self, content, filename=None):
        raw = content.encode("utf-8")
        name = filename or "image.svg"
        return {"file_data": base64.b64encode(raw).decode(), "file_name": name, "file_type": "svg", "mime": "image/svg+xml"}

    def _generate_json(self, content, filename=None):
        try:
            parsed = json.loads(content) if isinstance(content, str) else content
            raw = json.dumps(parsed, indent=2).encode("utf-8")
        except Exception:
            raw = content.encode("utf-8")
        name = filename or "data.json"
        return {"file_data": base64.b64encode(raw).decode(), "file_name": name, "file_type": "json", "mime": "application/json"}

    def _generate_html(self, content, filename=None):
        raw = content.encode("utf-8")
        name = filename or "page.html"
        return {"file_data": base64.b64encode(raw).decode(), "file_name": name, "file_type": "html", "mime": "text/html"}

    def _generate_text(self, content, filename=None, ext="txt"):
        raw = content.encode("utf-8")
        name = filename or f"file.{ext}"
        mimes = {"txt": "text/plain", "md": "text/markdown"}
        return {"file_data": base64.b64encode(raw).decode(), "file_name": name, "file_type": ext, "mime": mimes.get(ext, "text/plain")}
