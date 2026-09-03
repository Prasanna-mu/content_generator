import json
import sys
from pathlib import Path
from typing import Optional
from core.models.schemas import (
    UserInput, ContentQuality, ContentLength, QuizDifficulty
)


def get_user_input() -> UserInput:
    print("=" * 60)
    print("Content Generator - Sprint 1")
    print("=" * 60)
    print()

    prompt = get_required_input("Enter the main topic/prompt: ")
    
    num_lessons = get_int_input(
        "Number of lessons (1-50): ", 
        min_val=1, max_val=50, default=5
    )
    
    subtopics_per_lesson = get_int_input(
        "Subtopics per lesson (1-20): ", 
        min_val=1, max_val=20, default=4
    )
    
    content_quality = get_enum_input(
        "Content quality [technical/intermediate/beginner]: ",
        ContentQuality,
        default=ContentQuality.INTERMEDIATE
    )
    
    content_length = get_enum_input(
        "Content length [extreme/long/medium/simple]: ",
        ContentLength,
        default=ContentLength.MEDIUM
    )
    
    quiz_question_count = get_int_input(
        "Quiz questions per lesson (1-50): ",
        min_val=1, max_val=50, default=5
    )
    
    quiz_difficulty = get_enum_input(
        "Quiz difficulty [technical/intermediate/beginner]: ",
        QuizDifficulty,
        default=QuizDifficulty.INTERMEDIATE
    )
    
    question_bank_count = get_int_input(
        "Question bank questions per lesson (1-100): ",
        min_val=1, max_val=100, default=10
    )

    web_search_needed = confirm("Enable web search for content enrichment? (y/n): ")

    user_input = UserInput(
        prompt=prompt,
        num_lessons=num_lessons,
        subtopics_per_lesson=subtopics_per_lesson,
        content_quality=content_quality,
        content_length=content_length,
        quiz_question_count=quiz_question_count,
        quiz_difficulty=quiz_difficulty,
        question_bank_count=question_bank_count,
        web_search_needed=web_search_needed
    )

    print("\n" + "=" * 60)
    print("Configuration Summary:")
    print("=" * 60)
    print(json.dumps(user_input.model_dump(), indent=2))
    print("=" * 60)
    
    if not confirm("Proceed with generation? (y/n): "):
        print("Cancelled.")
        sys.exit(0)

    return user_input


def get_required_input(prompt: str) -> str:
    while True:
        value = input(prompt).strip()
        if value:
            return value
        print("This field is required. Please enter a value.")


def get_int_input(prompt: str, min_val: int, max_val: int, default: int) -> int:
    while True:
        value = input(f"{prompt} [{default}]: ").strip()
        if not value:
            return default
        try:
            num = int(value)
            if min_val <= num <= max_val:
                return num
            print(f"Please enter a number between {min_val} and {max_val}.")
        except ValueError:
            print("Please enter a valid integer.")


def get_enum_input(prompt: str, enum_class: type, default: str) -> str:
    valid_values = [e.value for e in enum_class]
    while True:
        value = input(f"{prompt} [{default.value}]: ").strip().lower()
        if not value:
            return default
        if value in valid_values:
            return enum_class(value)
        print(f"Invalid option. Choose from: {', '.join(valid_values)}")


def confirm(prompt: str) -> bool:
    while True:
        value = input(prompt).strip().lower()
        if value in ('y', 'yes'):
            return True
        if value in ('n', 'no'):
            return False
        print("Please enter 'y' or 'n'.")


def save_user_input_json(user_input: UserInput, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "user_input.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(user_input.model_dump(), f, indent=2, ensure_ascii=False)
    return json_path


def load_user_input_json(json_path: Path) -> UserInput:
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return UserInput(**data)


if __name__ == "__main__":
    user_input = get_user_input()
    output_dir = Path("output") / user_input.prompt.replace(" ", "_").replace("/", "_")
    json_path = save_user_input_json(user_input, output_dir)
    print(f"\nUser input saved to: {json_path}")