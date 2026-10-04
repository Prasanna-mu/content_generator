import csv
import json
import re
from pathlib import Path
from typing import List, Optional
from core.models.schemas import UserInput, LessonOutput, GeneratedContent, QuizQuestion, QuestionBankItem, WebSearchReport

try:
    from docx import Document
    from docx.shared import Inches, Pt, Cm, RGBColor, Emu
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.style import WD_STYLE_TYPE
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.oxml.ns import qn, nsdecls
    from docx.oxml import parse_xml
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False
    Document = None


class OutputWriter:
    def __init__(self, base_output_dir: Path):
        self.base_output_dir = base_output_dir

    def write_all(self, user_input: UserInput, lesson_outputs: List[LessonOutput], web_search_report: Optional[WebSearchReport] = None, session_id: Optional[str] = None) -> Path:
        if session_id:
            output_dir = self.base_output_dir / session_id
        else:
            prompt_folder = self._sanitize_folder_name(user_input.prompt)
            output_dir = self.base_output_dir / prompt_folder
        output_dir.mkdir(parents=True, exist_ok=True)
        
        self._write_user_input_json(user_input, output_dir)
        
        for lesson_output in lesson_outputs:
            self._write_lesson_output(lesson_output, output_dir)
        
        self._write_summary_json(user_input, lesson_outputs, output_dir)
        
        if web_search_report:
            self._write_web_search_references(web_search_report, output_dir)
        
        print(f"\nOutput written to: {output_dir}")
        return output_dir

    def _write_user_input_json(self, user_input: UserInput, output_dir: Path):
        json_path = output_dir / "user_input.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(user_input.model_dump(), f, indent=2, ensure_ascii=False)

    def _write_lesson_output(self, lesson_output: LessonOutput, base_dir: Path):
        lesson_folder = self._sanitize_folder_name(lesson_output.lesson.title)
        lesson_dir = base_dir / lesson_folder
        lesson_dir.mkdir(parents=True, exist_ok=True)
        
        for content in lesson_output.generated_contents:
            self._write_subtopic_content(content, lesson_dir)
        
        self._write_quiz_csv(lesson_output.quiz_questions, lesson_dir)
        self._write_question_bank_csv(lesson_output.question_bank, lesson_dir)
        self._write_lesson_summary_json(lesson_output, lesson_dir)

    def _write_subtopic_content(self, content: GeneratedContent, lesson_dir: Path):
        """
        DEPRECATED: TXT files are now written by _run_content_generation to ensure
        single authoritative writer and correct naming.
        This method is kept for backward compatibility but does nothing.
        """
        pass

    def _write_quiz_csv(self, quiz_questions: List[QuizQuestion], lesson_dir: Path):
        file_path = lesson_dir / "quiz.csv"
        with open(file_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["Question", "Option A", "Option B", "Option C", "Option D", "Correct Answer", "Explanation", "Knowledge Level"])
            for q in quiz_questions:
                writer.writerow([
                    q.question,
                    q.options[0] if len(q.options) > 0 else "",
                    q.options[1] if len(q.options) > 1 else "",
                    q.options[2] if len(q.options) > 2 else "",
                    q.options[3] if len(q.options) > 3 else "",
                    q.correct_answer,
                    q.explanation,
                    q.k_level
                ])

    def _write_question_bank_csv(self, question_bank: List[QuestionBankItem], lesson_dir: Path):
        file_path = lesson_dir / "question_bank.csv"
        with open(file_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["Question", "Answer", "Difficulty", "Knowledge Level"])
            for q in question_bank:
                writer.writerow([q.question, q.answer, q.difficulty, q.k_level])

    def _write_lesson_summary_json(self, lesson_output: LessonOutput, lesson_dir: Path):
        summary = {
            "lesson_title": lesson_output.lesson.title,
            "lesson_description": lesson_output.lesson.description,
            "subtopics": [
                {
                    "title": s.title,
                    "description": s.description,
                    "estimated_chars": s.estimated_chars,
                    "actual_chars": next((c.actual_chars for c in lesson_output.generated_contents if c.subtopic_title == s.title), 0)
                }
                for s in lesson_output.lesson.subtopics
            ],
            "quiz_question_count": len(lesson_output.quiz_questions),
            "question_bank_count": len(lesson_output.question_bank)
        }
        file_path = lesson_dir / "lesson_summary.json"
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

    def _write_summary_json(self, user_input: UserInput, lesson_outputs: List[LessonOutput], output_dir: Path):
        summary = {
            "prompt": user_input.prompt,
            "config": user_input.model_dump(),
            "total_lessons": len(lesson_outputs),
            "total_subtopics": sum(len(lo.lesson.subtopics) for lo in lesson_outputs),
            "total_content_chars": sum(
                c.actual_chars for lo in lesson_outputs for c in lo.generated_contents
            ),
            "total_quiz_questions": sum(len(lo.quiz_questions) for lo in lesson_outputs),
            "total_question_bank_items": sum(len(lo.question_bank) for lo in lesson_outputs),
            "lessons": [
                {
                    "title": lo.lesson.title,
                    "subtopic_count": len(lo.lesson.subtopics),
                    "total_chars": sum(c.actual_chars for c in lo.generated_contents)
                }
                for lo in lesson_outputs
            ]
        }
        file_path = output_dir / "generation_summary.json"
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

    def _write_web_search_references(self, report: WebSearchReport, output_dir: Path):
        file_path = output_dir / "references.txt"
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write("WEB SEARCH REFERENCES REPORT\n")
            f.write("=" * 80 + "\n\n")
            f.write(f"Topic: {report.user_prompt}\n")
            f.write(f"Search Timestamp: {report.search_timestamp}\n")
            f.write(f"Total Search Queries: {len(report.search_queries)}\n")
            f.write(f"Total Results Found: {report.total_results}\n")
            f.write(f"Reputable Sources: {report.reputable_results}\n\n")
            
            f.write("-" * 80 + "\n")
            f.write("SEARCH QUERIES USED:\n")
            f.write("-" * 80 + "\n")
            for i, query in enumerate(report.search_queries, 1):
                f.write(f"  {i}. {query}\n")
            f.write("\n")
            
            f.write("-" * 80 + "\n")
            f.write("DETAILED RESULTS:\n")
            f.write("-" * 80 + "\n\n")
            
            reputable_results = [r for r in report.results if r.is_reputable]
            
            for i, result in enumerate(reputable_results, 1):
                f.write(f"[{i}] {result.title}\n")
                f.write(f"    URL: {result.url}\n")
                f.write(f"    Search Query: {result.query}\n")
                f.write(f"    Reputation Score: {result.reputation_score:.2f}\n")
                f.write(f"    Extracted At: {result.extracted_at}\n")
                if result.snippet:
                    f.write(f"    Snippet: {result.snippet[:200]}...\n")
                if result.analysis:
                    f.write(f"    Analysis: {result.analysis[:500]}...\n")
                if result.normalized_content:
                    f.write(f"    Normalized Content (first 1000 chars):\n")
                    f.write(f"    {result.normalized_content[:1000]}\n")
                f.write("\n" + "-" * 80 + "\n\n")
            
            if len(report.results) > len(reputable_results):
                f.write("\nNON-REPUTABLE SOURCES (EXCLUDED FROM CONTENT):\n")
                f.write("-" * 80 + "\n")
                for result in report.results:
                    if not result.is_reputable:
                        f.write(f"  - {result.title} ({result.url}) - Score: {result.reputation_score:.2f}\n")
        
        print(f"  References written to: {file_path}")

    def _sanitize_folder_name(self, name: str) -> str:
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            name = name.replace(char, '_')
        return name.strip().replace(' ', '_')[:100]


class DOCXWriter:
    """
    Professional DOCX writer that converts Markdown content to formatted Word documents.
    Supports:
    - Heading 1-4 hierarchy with professional styling
    - Bullet lists and nested bullet lists
    - Numbered lists (including bold-numbered items like **1. Item**)
    - Bold, italic, inline code formatting
    - Code blocks with monospace font and background shading
    - Tables with professional styling
    - Consistent fonts, margins, paragraph spacing
    - Page numbers, headers, and footers
    - Removes duplicate Lesson/Subtopic titles from content
    """

    DEFAULT_FONT = "Calibri"
    DEFAULT_FONT_SIZE = Pt(11)
    HEADING_FONT = "Calibri Light"
    CODE_FONT = "Consolas"
    CODE_FONT_SIZE = Pt(9.5)
    MARGIN_TOP = Cm(2.54)
    MARGIN_BOTTOM = Cm(2.54)
    MARGIN_LEFT = Cm(2.54)
    MARGIN_RIGHT = Cm(2.54)

    def __init__(self):
        if not DOCX_AVAILABLE:
            raise ImportError("python-docx is required for DOCX export. Install with: pip install python-docx")

    def create_document(self, lesson_number: int, lesson_title: str, subtopic_number: int, subtopic_title: str,
                        co: str = "N/A", po: str = "N/A", k_level: str = "N/A") -> Document:
        """Create a new document with professional page setup, styles, and header/footer."""
        doc = Document()

        # Page setup
        for section in doc.sections:
            section.top_margin = self.MARGIN_TOP
            section.bottom_margin = self.MARGIN_BOTTOM
            section.left_margin = self.MARGIN_LEFT
            section.right_margin = self.MARGIN_RIGHT

            # Add page numbers to footer
            self._add_page_numbers(section)

            # Add header with lesson info
            self._add_header(section, lesson_number, lesson_title, subtopic_number, subtopic_title)

        # Configure styles
        self._configure_styles(doc)

        # Title page / Document header
        title = doc.add_heading(f"Lesson {lesson_number}: {lesson_title}", level=1)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        title.paragraph_format.space_after = Pt(6)

        subtopic_heading = doc.add_heading(f"Subtopic {subtopic_number}: {subtopic_title}", level=2)
        subtopic_heading.paragraph_format.space_after = Pt(12)

        # Metadata table
        table = doc.add_table(rows=5, cols=2, style='Table Grid')
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        self._style_metadata_table(table)
        table.cell(0, 0).text = "Lesson"
        table.cell(0, 1).text = f"{lesson_number}: {lesson_title}"
        table.cell(1, 0).text = "Subtopic"
        table.cell(1, 1).text = f"{subtopic_number}: {subtopic_title}"
        table.cell(2, 0).text = "Course Outcome (CO)"
        table.cell(2, 1).text = co
        table.cell(3, 0).text = "Program Outcome (PO)"
        table.cell(3, 1).text = po
        table.cell(4, 0).text = "Knowledge Level (K-Level)"
        table.cell(4, 1).text = k_level

        # Set column widths
        for row in table.rows:
            row.cells[0].width = Cm(4.5)
            row.cells[1].width = Cm(12.5)

        # Content heading
        doc.add_heading("Content", level=2).paragraph_format.space_after = Pt(12)

        return doc

    def _configure_styles(self, doc: Document):
        """Configure professional document styles."""
        style = doc.styles['Normal']
        font = style.font
        font.name = self.DEFAULT_FONT
        font.size = self.DEFAULT_FONT_SIZE
        font.color.rgb = RGBColor(0x33, 0x33, 0x33)
        style.paragraph_format.space_after = Pt(6)
        style.paragraph_format.space_before = Pt(0)
        style.paragraph_format.line_spacing = 1.15

        # Heading styles
        for level in range(1, 5):
            heading_style = doc.styles[f'Heading {level}']
            heading_style.font.name = self.HEADING_FONT
            heading_style.font.color.rgb = RGBColor(0x1F, 0x3A, 0x5F)
            if level == 1:
                heading_style.font.size = Pt(24)
                heading_style.font.bold = True
                heading_style.paragraph_format.space_before = Pt(24)
                heading_style.paragraph_format.space_after = Pt(12)
            elif level == 2:
                heading_style.font.size = Pt(18)
                heading_style.font.bold = True
                heading_style.paragraph_format.space_before = Pt(18)
                heading_style.paragraph_format.space_after = Pt(10)
            elif level == 3:
                heading_style.font.size = Pt(14)
                heading_style.font.bold = True
                heading_style.paragraph_format.space_before = Pt(14)
                heading_style.paragraph_format.space_after = Pt(8)
            elif level == 4:
                heading_style.font.size = Pt(12)
                heading_style.font.bold = True
                heading_style.paragraph_format.space_before = Pt(10)
                heading_style.paragraph_format.space_after = Pt(6)

        # List Bullet style
        if 'List Bullet' in doc.styles:
            bullet_style = doc.styles['List Bullet']
            bullet_style.font.name = self.DEFAULT_FONT
            bullet_style.font.size = self.DEFAULT_FONT_SIZE
            bullet_style.paragraph_format.space_after = Pt(2)
            bullet_style.paragraph_format.space_before = Pt(2)
            bullet_style.paragraph_format.left_indent = Cm(1.27)
            bullet_style.paragraph_format.first_line_indent = Cm(-0.63)

        # List Number style
        if 'List Number' in doc.styles:
            number_style = doc.styles['List Number']
            number_style.font.name = self.DEFAULT_FONT
            number_style.font.size = self.DEFAULT_FONT_SIZE
            number_style.paragraph_format.space_after = Pt(2)
            number_style.paragraph_format.space_before = Pt(2)
            number_style.paragraph_format.left_indent = Cm(1.27)
            number_style.paragraph_format.first_line_indent = Cm(-0.63)

        # Code block style (custom)
        if 'Code Block' not in doc.styles:
            code_style = doc.styles.add_style('Code Block', WD_STYLE_TYPE.PARAGRAPH)
        else:
            code_style = doc.styles['Code Block']
        code_style.font.name = self.CODE_FONT
        code_style.font.size = self.CODE_FONT_SIZE
        code_style.font.color.rgb = RGBColor(0x2D, 0x2D, 0x2D)
        code_style.paragraph_format.space_after = Pt(6)
        code_style.paragraph_format.space_before = Pt(6)
        code_style.paragraph_format.left_indent = Cm(1.0)
        code_style.paragraph_format.right_indent = Cm(1.0)
        # Add shading to code block style
        shading_elm = parse_xml(f'<w:shd {nsdecls("w")} w:fill="F4F4F4" w:val="clear"/>')
        code_style.paragraph_format.element.get_or_add_pPr().append(shading_elm)

    def _add_page_numbers(self, section):
        """Add page numbers to footer."""
        footer = section.footer
        footer.is_linked_to_previous = False
        para = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = para.add_run()
        fldChar1 = parse_xml(f'<w:fldChar {nsdecls("w")} w:fldCharType="begin"/>')
        run._r.append(fldChar1)
        run2 = para.add_run()
        instrText = parse_xml(f'<w:instrText {nsdecls("w")} xml:space="preserve"> PAGE </w:instrText>')
        run2._r.append(instrText)
        run3 = para.add_run()
        fldChar2 = parse_xml(f'<w:fldChar {nsdecls("w")} w:fldCharType="end"/>')
        run3._r.append(fldChar2)
        para.paragraph_format.space_before = Pt(0)
        para.paragraph_format.space_after = Pt(0)

    def _add_header(self, section, lesson_number: int, lesson_title: str, subtopic_number: int, subtopic_title: str):
        """Add header with lesson and subtopic info."""
        header = section.header
        header.is_linked_to_previous = False
        para = header.paragraphs[0] if header.paragraphs else header.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.LEFT
        run = para.add_run(f"Lesson {lesson_number}: {lesson_title}  |  Subtopic {subtopic_number}: {subtopic_title}")
        run.font.name = self.DEFAULT_FONT
        run.font.size = Pt(8)
        run.font.color.rgb = RGBColor(0x80, 0x80, 0x80)
        run.italic = True
        para.paragraph_format.space_before = Pt(0)
        para.paragraph_format.space_after = Pt(0)
        # Add bottom border to header
        pPr = para._p.get_or_add_pPr()
        pBdr = parse_xml(f'<w:pBdr {nsdecls("w")}><w:bottom w:val="single" w:sz="4" w:space="1" w:color="CCCCCC"/></w:pBdr>')
        pPr.append(pBdr)

    def _style_metadata_table(self, table):
        """Apply professional styling to metadata table."""
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    paragraph.paragraph_format.space_before = Pt(2)
                    paragraph.paragraph_format.space_after = Pt(2)
                    for run in paragraph.runs:
                        run.font.name = self.DEFAULT_FONT
                        run.font.size = Pt(10)
                # Header column styling
                if cell == row.cells[0]:
                    shading_elm = parse_xml(f'<w:shd {nsdecls("w")} w:fill="E8F0FE" w:val="clear"/>')
                    cell._tc.get_or_add_tcPr().append(shading_elm)
                    for paragraph in cell.paragraphs:
                        for run in paragraph.runs:
                            run.bold = True
                            run.font.size = Pt(10)

    def add_markdown_content(self, doc: Document, markdown_text: str, lesson_title: str = "", subtopic_title: str = ""):
        """
        Convert Markdown text to professional Word formatting.
        Removes duplicate lesson/subtopic titles from content.
        """
        lines = markdown_text.split('\n')
        i = 0
        in_code_block = False
        code_block_lines = []
        code_block_lang = ""
        list_stack = []  # Track nested list levels

        while i < len(lines):
            line = lines[i]
            original_line = line

            # Skip duplicate lesson/subtopic titles at the beginning
            if i < 5:
                stripped_check = line.strip()
                if (stripped_check.startswith('#') and
                    (lesson_title.lower() in stripped_check.lower() or
                     subtopic_title.lower() in stripped_check.lower())):
                    i += 1
                    continue

            if line.strip().startswith('```'):
                if not in_code_block:
                    in_code_block = True
                    code_block_lines = []
                    code_block_lang = line.strip()[3:].strip()
                else:
                    in_code_block = False
                    if code_block_lines:
                        self._add_code_block(doc, code_block_lines, code_block_lang)
                i += 1
                continue

            if in_code_block:
                code_block_lines.append(line)
                i += 1
                continue

            stripped = line.lstrip()
            leading_spaces = len(line) - len(stripped)

            # Heading 1-4
            if stripped.startswith('# '):
                heading_text = stripped[2:].strip()
                heading = doc.add_heading(heading_text, level=1)
                i += 1
                continue

            if stripped.startswith('## '):
                heading_text = stripped[3:].strip()
                heading = doc.add_heading(heading_text, level=2)
                i += 1
                continue

            if stripped.startswith('### '):
                heading_text = stripped[4:].strip()
                heading = doc.add_heading(heading_text, level=3)
                i += 1
                continue

            if stripped.startswith('#### '):
                heading_text = stripped[5:].strip()
                heading = doc.add_heading(heading_text, level=4)
                i += 1
                continue

            # Numbered list items (1. item, 2. item) OR bold-numbered (**1. Item**)
            # Handle both: 1. Item and **1. Item** (with optional trailing **)
            # Use original line to preserve leading whitespace for nesting detection
            numbered_match = re.match(r'^(\s*)(\*\*)?(\d+)\.\s+(.+)', line)
            if numbered_match:
                indent = numbered_match.group(1)
                is_bold = numbered_match.group(2) is not None
                number = numbered_match.group(3)
                text = numbered_match.group(4)
                # Strip trailing ** if present (for **1. Item** format)
                if text.endswith('**'):
                    text = text[:-2]

                level = len(indent) // 2 if indent else 0
                para = doc.add_paragraph(style='List Number')
                self._set_list_level(para, level)
                if is_bold:
                    run = para.add_run(f"{number}. ")
                    run.bold = True
                    run.font.size = self.DEFAULT_FONT_SIZE
                    run.font.name = self.DEFAULT_FONT
                    self._add_formatted_text(para, text)
                else:
                    # Remove the number prefix since List Number adds it automatically
                    self._add_formatted_text(para, text)
                para.paragraph_format.space_after = Pt(2)
                para.paragraph_format.space_before = Pt(2)
                i += 1
                continue

            # Bullet lists (- item, * item) with nesting support
            # Use original line to preserve leading whitespace for nesting detection
            bullet_match = re.match(r'^(\s*)([-*])\s+(.+)', line)
            if bullet_match:
                indent = bullet_match.group(1)
                bullet_char = bullet_match.group(2)
                text = bullet_match.group(3)

                level = len(indent) // 2 if indent else 0
                para = doc.add_paragraph(style='List Bullet')
                self._set_list_level(para, level)
                self._add_formatted_text(para, text)
                para.paragraph_format.space_after = Pt(2)
                para.paragraph_format.space_before = Pt(2)
                i += 1
                continue

            # Empty line - add small spacing
            if stripped == '':
                i += 1
                continue

            # Regular paragraph
            para = doc.add_paragraph()
            self._add_formatted_text(para, line)
            para.paragraph_format.space_after = Pt(6)
            i += 1

    def _set_list_level(self, paragraph, level: int):
        """Set the list level for nested lists."""
        if level > 0:
            pPr = paragraph._p.get_or_add_pPr()
            numPr = parse_xml(f'<w:numPr {nsdecls("w")}><w:ilvl w:val="{min(level, 8)}"/></w:numPr>')
            pPr.append(numPr)
            paragraph.paragraph_format.left_indent = Cm(1.27 + level * 0.63)
            paragraph.paragraph_format.first_line_indent = Cm(-0.63)

    def _add_formatted_text(self, paragraph, text: str):
        """
        Add text to a paragraph with bold/italic/code formatting.
        Supports **bold**, *italic*, `code`, and handles escaped characters.
        """
        from docx.shared import Pt, RGBColor

        # Split by formatting markers while preserving them
        parts = re.split(r'(\*\*.*?\*\*|\*.*?\*|`.*?`)', text)

        for part in parts:
            if part.startswith('**') and part.endswith('**') and len(part) > 4:
                run = paragraph.add_run(part[2:-2])
                run.bold = True
                run.font.name = self.DEFAULT_FONT
                run.font.size = self.DEFAULT_FONT_SIZE
            elif part.startswith('*') and part.endswith('*') and len(part) > 2 and not part.startswith('**'):
                run = paragraph.add_run(part[1:-1])
                run.italic = True
                run.font.name = self.DEFAULT_FONT
                run.font.size = self.DEFAULT_FONT_SIZE
            elif part.startswith('`') and part.endswith('`') and len(part) > 2:
                run = paragraph.add_run(part[1:-1])
                run.font.name = self.CODE_FONT
                run.font.size = self.CODE_FONT_SIZE
                run.font.color.rgb = RGBColor(0x2D, 0x2D, 0x2D)
            else:
                run = paragraph.add_run(part)
                run.font.name = self.DEFAULT_FONT
                run.font.size = self.DEFAULT_FONT_SIZE
            # Ensure default font properties
            run.font.color.rgb = RGBColor(0x33, 0x33, 0x33)

    def _add_code_block(self, doc: Document, code_lines: List[str], language: str = ""):
        """Add a formatted code block with optional language label."""
        if not code_lines:
            return

        # Add language label if provided
        if language:
            lang_para = doc.add_paragraph()
            lang_para.paragraph_format.space_after = Pt(0)
            lang_para.paragraph_format.space_before = Pt(6)
            lang_para.paragraph_format.left_indent = Cm(1.0)
            run = lang_para.add_run(language)
            run.font.name = self.CODE_FONT
            run.font.size = Pt(8)
            run.font.color.rgb = RGBColor(0x80, 0x80, 0x80)
            run.italic = True

        # Add code content
        code_text = '\n'.join(code_lines)
        code_para = doc.add_paragraph(style='Code Block')
        # Split by lines to preserve formatting
        for line_idx, code_line in enumerate(code_lines):
            if line_idx > 0:
                run = code_para.add_run('\n')
                run.font.name = self.CODE_FONT
                run.font.size = self.CODE_FONT_SIZE
            run = code_para.add_run(code_line)
            run.font.name = self.CODE_FONT
            run.font.size = self.CODE_FONT_SIZE
            run.font.color.rgb = RGBColor(0x2D, 0x2D, 0x2D)

    def save(self, doc: Document, file_path: Path):
        """Save document with error handling."""
        file_path.parent.mkdir(parents=True, exist_ok=True)
        doc.save(file_path)