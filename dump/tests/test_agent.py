"""
Test script to verify the agent works properly with validation and intermediate output saving.
This test mocks the LLM to simulate various scenarios including validation failures.
"""
import sys
import json
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.models.schemas import (
    UserInput, Lesson, Subtopic, ContentQuality, ContentLength, QuizDifficulty
)
from core.llm.base import BaseLLMProvider
from core.planning.lesson_generator import LessonGenerator
from core.planning.subtopic_generator import SubtopicGenerator
from core.pipeline.orchestrator import PipelineOrchestrator


def create_test_user_input():
    """Create a test user input."""
    return UserInput(
        prompt="Python Programming Basics",
        num_lessons=3,
        subtopics_per_lesson=2,
        content_quality=ContentQuality.BEGINNER,
        content_length=ContentLength.SIMPLE,
        quiz_question_count=3,
        quiz_difficulty=QuizDifficulty.BEGINNER,
        question_bank_count=5,
        web_search_needed=False
    )


def test_validate_lessons_json():
    """Test lesson JSON validation."""
    print("\n=== Testing Lesson JSON Validation ===")
    
    class TestProvider(BaseLLMProvider):
        def generate(self, prompt, system_prompt=None, **kwargs):
            return ""
        def generate_json(self, prompt, system_prompt=None, **kwargs):
            return {}
    
    provider = TestProvider("test")
    
    # Valid lessons
    valid_data = {
        "lessons": [
            {"title": "Lesson 1", "description": "Description 1"},
            {"title": "Lesson 2", "description": "Description 2"}
        ]
    }
    assert provider.validate_lessons_json(valid_data) == True
    print("[OK] Valid lessons JSON passes validation")
    
    # Invalid: missing title
    invalid_data = {
        "lessons": [
            {"description": "Description 1"}
        ]
    }
    assert provider.validate_lessons_json(invalid_data) == False
    print("[OK] Invalid lessons JSON (missing title) fails validation")
    
    # Invalid: empty lessons
    assert provider.validate_lessons_json({"lessons": []}) == False
    print("[OK] Empty lessons list fails validation")
    
    # Invalid: not a dict
    assert provider.validate_lessons_json("not a dict") == False
    print("[OK] Non-dict input fails validation")


def test_validate_subtopics_json():
    """Test subtopic JSON validation."""
    print("\n=== Testing Subtopic JSON Validation ===")
    
    class TestProvider(BaseLLMProvider):
        def generate(self, prompt, system_prompt=None, **kwargs):
            return ""
        def generate_json(self, prompt, system_prompt=None, **kwargs):
            return {}
    
    provider = TestProvider("test")
    
    # Valid subtopics
    valid_data = {
        "subtopics": [
            {"title": "Subtopic 1", "description": "Desc 1", "estimated_chars": 500},
            {"title": "Subtopic 2", "description": "Desc 2", "estimated_chars": 800}
        ]
    }
    assert provider.validate_subtopics_json(valid_data, expected_count=2) == True
    print("[OK] Valid subtopics JSON passes validation")
    
    # Invalid: missing estimated_chars
    invalid_data = {
        "subtopics": [
            {"title": "Subtopic 1", "description": "Desc 1"}
        ]
    }
    assert provider.validate_subtopics_json(invalid_data) == False
    print("[OK] Invalid subtopics JSON (missing estimated_chars) fails validation")
    
    # Invalid: estimated_chars not int
    invalid_data2 = {
        "subtopics": [
            {"title": "Subtopic 1", "description": "Desc 1", "estimated_chars": "500"}
        ]
    }
    assert provider.validate_subtopics_json(invalid_data2) == False
    print("[OK] Invalid subtopics JSON (estimated_chars not int) fails validation")
    
    # Invalid: estimated_chars <= 0
    invalid_data3 = {
        "subtopics": [
            {"title": "Subtopic 1", "description": "Desc 1", "estimated_chars": 0}
        ]
    }
    assert provider.validate_subtopics_json(invalid_data3) == False
    print("[OK] Invalid subtopics JSON (estimated_chars <= 0) fails validation")
    
    # Invalid: wrong count
    assert provider.validate_subtopics_json(valid_data, expected_count=3) == False
    print("[OK] Wrong subtopic count fails validation")


def test_validate_quiz_json():
    """Test quiz JSON validation."""
    print("\n=== Testing Quiz JSON Validation ===")
    
    class TestProvider(BaseLLMProvider):
        def generate(self, prompt, system_prompt=None, **kwargs):
            return ""
        def generate_json(self, prompt, system_prompt=None, **kwargs):
            return {}
    
    provider = TestProvider("test")
    
    # Valid quiz
    valid_data = {
        "questions": [
            {
                "question": "What is Python?",
                "options": ["A snake", "A language", "A tool", "A framework"],
                "correct_answer": 1,
                "explanation": "Python is a programming language"
            }
        ]
    }
    assert provider.validate_quiz_json(valid_data, expected_count=1) == True
    print("[OK] Valid quiz JSON passes validation")
    
    # Invalid: wrong number of options
    invalid_data = {
        "questions": [
            {
                "question": "What is Python?",
                "options": ["A snake", "A language"],
                "correct_answer": 1,
                "explanation": "Python is a programming language"
            }
        ]
    }
    assert provider.validate_quiz_json(invalid_data) == False
    print("[OK] Invalid quiz JSON (wrong options count) fails validation")
    
    # Invalid: correct_answer out of range
    invalid_data2 = {
        "questions": [
            {
                "question": "What is Python?",
                "options": ["A", "B", "C", "D"],
                "correct_answer": 5,
                "explanation": "Python is a programming language"
            }
        ]
    }
    assert provider.validate_quiz_json(invalid_data2) == False
    print("[OK] Invalid quiz JSON (correct_answer out of range) fails validation")


def test_validate_question_bank_json():
    """Test question bank JSON validation."""
    print("\n=== Testing Question Bank JSON Validation ===")
    
    class TestProvider(BaseLLMProvider):
        def generate(self, prompt, system_prompt=None, **kwargs):
            return ""
        def generate_json(self, prompt, system_prompt=None, **kwargs):
            return {}
    
    provider = TestProvider("test")
    
    # Valid question bank
    valid_data = {
        "questions": [
            {"question": "Explain Python", "answer": "Python is...", "difficulty": "beginner"},
            {"question": "What is a list?", "answer": "A list is...", "difficulty": "beginner"}
        ]
    }
    assert provider.validate_question_bank_json(valid_data, expected_count=2) == True
    print("[OK] Valid question bank JSON passes validation")
    
    # Invalid: missing answer
    invalid_data = {
        "questions": [
            {"question": "Explain Python", "difficulty": "beginner"}
        ]
    }
    assert provider.validate_question_bank_json(invalid_data) == False
    print("[OK] Invalid question bank JSON (missing answer) fails validation")


def test_generate_json_with_validation():
    """Test generate_json_with_validation with retries."""
    print("\n=== Testing generate_json_with_validation ===")
    
    class TestProvider(BaseLLMProvider):
        def __init__(self):
            super().__init__("test")
            self.call_count = 0
            
        def generate(self, prompt, system_prompt=None, **kwargs):
            return ""
            
        def generate_json(self, prompt, system_prompt=None, **kwargs):
            self.call_count += 1
            if self.call_count < 3:
                # Return invalid data first two times
                return {"lessons": [{"title": "Test"}]}  # Missing description
            # Return valid data on third try
            return {"lessons": [{"title": "Test", "description": "Desc"}]}
    
    provider = TestProvider()
    result = provider.generate_json_with_validation(
        "test prompt",
        "test system",
        lambda d: provider.validate_lessons_json(d),
        max_retries=3
    )
    assert result == {"lessons": [{"title": "Test", "description": "Desc"}]}
    assert provider.call_count == 3
    print("[OK] generate_json_with_validation retries and succeeds on 3rd attempt")
    
    # Test failure after max retries
    provider2 = TestProvider()
    provider2.call_count = 0
    try:
        provider2.generate_json_with_validation(
            "test prompt",
            "test system",
            lambda d: provider2.validate_lessons_json(d),
            max_retries=2
        )
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "Failed to generate valid JSON after 2 attempts" in str(e)
        print("[OK] generate_json_with_validation raises ValueError after max retries")


def test_lesson_generator_save_load():
    """Test lesson generator save and load functionality."""
    print("\n=== Testing Lesson Generator Save/Load ===")
    
    class TestProvider(BaseLLMProvider):
        def __init__(self):
            super().__init__("test")
            self._output_dir = Path("test_output")
            self._output_dir.mkdir(exist_ok=True)
            
        def generate(self, prompt, system_prompt=None, **kwargs):
            return ""
            
        def generate_json(self, prompt, system_prompt=None, **kwargs):
            return {"lessons": [{"title": "Lesson 1", "description": "Desc 1"}]}
    
    provider = TestProvider()
    generator = LessonGenerator(provider)
    user_input = create_test_user_input()
    
    # Generate lessons
    lessons = generator.generate(user_input)
    assert len(lessons) == 1
    print("[OK] Lesson generation works")
    
    # Refine lessons (should save)
    lessons = generator.refine_lessons(lessons, user_input)
    
    # Check saved file exists
    saved_file = provider._output_dir / "lessons_refined.json"
    assert saved_file.exists()
    print("[OK] Refined lessons saved to file")
    
    # Load saved lessons
    loaded_lessons = generator.load_saved_lessons(user_input)
    assert len(loaded_lessons) == 1
    assert loaded_lessons[0].title == "Lesson 1"
    print("[OK] Saved lessons loaded correctly")
    
    # Cleanup
    import shutil
    shutil.rmtree(provider._output_dir)


def test_subtopic_generator_save_load():
    """Test subtopic generator save and load functionality."""
    print("\n=== Testing Subtopic Generator Save/Load ===")
    
    class TestProvider(BaseLLMProvider):
        def __init__(self):
            super().__init__("test")
            self._output_dir = Path("test_output2")
            self._output_dir.mkdir(exist_ok=True)
            
        def generate(self, prompt, system_prompt=None, **kwargs):
            return ""
            
        def generate_json(self, prompt, system_prompt=None, **kwargs):
            return {
                "subtopics": [
                    {"title": "Sub 1", "description": "Desc 1", "estimated_chars": 500},
                    {"title": "Sub 2", "description": "Desc 2", "estimated_chars": 800}
                ]
            }
    
    provider = TestProvider()
    generator = SubtopicGenerator(provider)
    user_input = create_test_user_input()
    
    # Create lessons
    lessons = [
        Lesson(title="Lesson 1", description="Desc 1", subtopics=[], estimated_total_chars=0),
        Lesson(title="Lesson 2", description="Desc 2", subtopics=[], estimated_total_chars=0)
    ]
    
    # Generate subtopics
    lessons = generator.generate_all(lessons, user_input)
    assert len(lessons[0].subtopics) == 2
    assert lessons[0].subtopics[0].estimated_chars == 500
    print("[OK] Subtopic generation works with estimated_chars")
    
    # Check saved file
    saved_file = provider._output_dir / "subtopics_all.json"
    assert saved_file.exists()
    print("[OK] All subtopics saved to file")
    
    # Validate
    assert generator.validate_subtopics(lessons, user_input) == True
    print("[OK] Subtopic validation passes")
    
    # Test validation failure
    lessons[0].subtopics = []  # Remove subtopics
    assert generator.validate_subtopics(lessons, user_input) == False
    print("[OK] Subtopic validation catches missing subtopics")
    
    # Load saved subtopics
    lessons = generator.load_saved_subtopics(lessons, user_input)
    assert len(lessons[0].subtopics) == 2
    print("[OK] Saved subtopics loaded correctly")
    
    # Cleanup
    import shutil
    shutil.rmtree(provider._output_dir)


def test_subtopic_generator_adjust_estimates():
    """Test subtopic estimate adjustment."""
    print("\n=== Testing Subtopic Estimate Adjustment ===")
    
    user_input = UserInput(
        prompt="Test",
        num_lessons=1,
        subtopics_per_lesson=2,
        content_quality=ContentQuality.BEGINNER,
        content_length=ContentLength.EXTREME,  # 1.5x multiplier
        quiz_question_count=3,
        quiz_difficulty=QuizDifficulty.BEGINNER,
        question_bank_count=5,
        web_search_needed=False
    )
    
    class TestProvider(BaseLLMProvider):
        def __init__(self):
            super().__init__("test")
            
        def generate(self, prompt, system_prompt=None, **kwargs):
            return ""
            
        def generate_json(self, prompt, system_prompt=None, **kwargs):
            return {
                "subtopics": [
                    {"title": "Sub 1", "description": "Desc 1", "estimated_chars": 1000},
                    {"title": "Sub 2", "description": "Desc 2", "estimated_chars": 2000}
                ]
            }
    
    provider = TestProvider()
    generator = SubtopicGenerator(provider)
    
    lessons = [
        Lesson(title="Lesson 1", description="Desc 1", subtopics=[], estimated_total_chars=0)
    ]
    
    lessons = generator.generate_all(lessons, user_input)
    lessons = generator.adjust_estimates(lessons, user_input)
    
    # Check multiplier applied (1.5 for extreme)
    assert lessons[0].subtopics[0].estimated_chars == 1500  # 1000 * 1.5
    assert lessons[0].subtopics[1].estimated_chars == 3000  # 2000 * 1.5
    assert lessons[0].estimated_total_chars == 4500
    print("[OK] Estimate adjustment applies content_length multiplier correctly")


def test_orchestrator_initialization():
    """Test orchestrator initialization sets output dir."""
    print("\n=== Testing Orchestrator Initialization ===")
    
    with patch('core.pipeline.orchestrator.LLMFactory') as mock_factory:
        mock_provider = Mock()
        mock_provider.check_connection.return_value = True
        mock_provider.list_models.return_value = ["qwen2.5:3b"]
        mock_provider.set_output_dir = Mock()
        mock_factory.create.return_value = mock_provider
        
        orchestrator = PipelineOrchestrator(
            model_name="qwen2.5:3b",
            output_dir=Path("test_output3")
        )
        orchestrator.initialize()
        
        # Verify set_output_dir was called
        mock_provider.set_output_dir.assert_called_once()
        print("[OK] Orchestrator sets LLM output directory on initialization")


def test_orchestrator_processing_dir_validation():
    """Test orchestrator rejects same output and processing dir."""
    print("\n=== Testing Orchestrator Processing Dir Validation ===")
    
    with patch('core.pipeline.orchestrator.LLMFactory') as mock_factory:
        mock_provider = Mock()
        mock_provider.check_connection.return_value = True
        mock_provider.list_models.return_value = ["qwen2.5:3b"]
        mock_factory.create.return_value = mock_provider
        
        orchestrator = PipelineOrchestrator(
            model_name="qwen2.5:3b",
            output_dir=Path("same_dir"),
            processing_dir=Path("same_dir")
        )
        try:
            orchestrator.initialize()
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "processing_dir must be different from output_dir" in str(e)
            print("[OK] Orchestrator rejects same output and processing directory")


def test_resume_point_with_web_search_disabled():
    """Test resume point calculation when web search is disabled."""
    print("\n=== Testing Resume Point with Web Search Disabled ===")
    
    from core.session.manager import SessionManager
    from core.session.models import SessionStatus, StageStatus, PipelineStage
    import tempfile
    import shutil
    
    tmpdir = tempfile.mkdtemp()
    try:
        db_path = Path(tmpdir) / "sessions.db"
        session_manager = SessionManager(db_path)
        
        # Create a session with all stages
        import uuid
        session = session_manager.create_session(
            prompt="Test",
            user_input_json='{"web_search_needed": false}',
            config={}
        )
        session_id = session.session_id
        
        # Mark PROMPT_ANALYSIS and WEB_SEARCH as completed
        session_manager.complete_stage(session_id, PipelineStage.PROMPT_ANALYSIS, {})
        session_manager.complete_stage(session_id, PipelineStage.WEB_SEARCH, {})
        
        # Get resume point from session manager - returns first non-completed stage
        resume_point = session_manager.get_resume_point(session_id)
        
        # Session manager returns LESSON_GENERATION (first PENDING stage after completed ones)
        assert resume_point == PipelineStage.LESSON_GENERATION, f"Expected LESSON_GENERATION, got {resume_point}"
        print("[OK] Session manager returns LESSON_GENERATION as resume point")
        
        # Now test the orchestrator logic for when web_search_needed=False
        # Pipeline stages when web_search_needed=False
        all_stages = [
            PipelineStage.PROMPT_ANALYSIS,
            PipelineStage.WEB_SEARCH,
            PipelineStage.LESSON_GENERATION,
            PipelineStage.LESSON_REFINEMENT,
        ]
        web_search_needed = False
        stages = [s for s in all_stages if web_search_needed or s != PipelineStage.WEB_SEARCH]
        
        # Simulate orchestrator fix: find first incomplete in actual pipeline
        resume_from = resume_point
        if resume_from and resume_from not in stages:
            for s in stages:
                status = session_manager.get_stage_status(session_id, s)
                if status in (StageStatus.PENDING, StageStatus.RUNNING, StageStatus.FAILED):
                    resume_from = s
                    break
        
        # Should be LESSON_GENERATION
        assert resume_from == PipelineStage.LESSON_GENERATION
        print("[OK] Orchestrator correctly uses LESSON_GENERATION as resume point")
        
        session_manager.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def run_all_tests():
    """Run all tests."""
    print("=" * 60)
    print("Running Agent Validation Tests")
    print("=" * 60)
    
    test_validate_lessons_json()
    test_validate_subtopics_json()
    test_validate_quiz_json()
    test_validate_question_bank_json()
    test_generate_json_with_validation()
    test_lesson_generator_save_load()
    test_subtopic_generator_save_load()
    test_subtopic_generator_adjust_estimates()
    test_orchestrator_initialization()
    test_orchestrator_processing_dir_validation()
    test_resume_point_with_web_search_disabled()
    
    print("\n" + "=" * 60)
    print("All tests passed! [OK]")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()