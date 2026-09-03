import csv
import json
from pathlib import Path
from typing import List
from core.models.schemas import UserInput, LessonOutput, GeneratedContent, QuizQuestion, QuestionBankItem


class OutputWriter:
    def __init__(self, base_output_dir: Path):
        self.base_output_dir = base_output_dir

    def write_all(self, user_input: UserInput, lesson_outputs: List[LessonOutput]) -> Path:
        prompt_folder = self._sanitize_folder_name(user_input.prompt)
        output_dir = self.base_output_dir / prompt_folder
        output_dir.mkdir(parents=True, exist_ok=True)
        
        self._write_user_input_json(user_input, output_dir)
        
        for lesson_output in lesson_outputs:
            self._write_lesson_output(lesson_output, output_dir)
        
        self._write_summary_json(user_input, lesson_outputs, output_dir)
        
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
        subtopic_folder = self._sanitize_folder_name(content.subtopic_title)
        subtopic_dir = lesson_dir / subtopic_folder
        subtopic_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = subtopic_dir / "content.txt"
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(f"Lesson: {content.lesson_title}\n")
            f.write(f"Subtopic: {content.subtopic_title}\n")
            f.write(f"Character Count: {content.actual_chars}\n")
            f.write("=" * 60 + "\n\n")
            f.write(content.content)

    def _write_quiz_csv(self, quiz_questions: List[QuizQuestion], lesson_dir: Path):
        file_path = lesson_dir / "quiz.csv"
        with open(file_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["Question", "Option A", "Option B", "Option C", "Option D", "Correct Answer", "Explanation"])
            for q in quiz_questions:
                writer.writerow([
                    q.question,
                    q.options[0] if len(q.options) > 0 else "",
                    q.options[1] if len(q.options) > 1 else "",
                    q.options[2] if len(q.options) > 2 else "",
                    q.options[3] if len(q.options) > 3 else "",
                    q.correct_answer,
                    q.explanation
                ])

    def _write_question_bank_csv(self, question_bank: List[QuestionBankItem], lesson_dir: Path):
        file_path = lesson_dir / "question_bank.csv"
        with open(file_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["Question", "Answer", "Difficulty"])
            for q in question_bank:
                writer.writerow([q.question, q.answer, q.difficulty])

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

    def _sanitize_folder_name(self, name: str) -> str:
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            name = name.replace(char, '_')
        return name.strip().replace(' ', '_')[:100]