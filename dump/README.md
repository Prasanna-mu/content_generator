# Content Generator - Sprint 1

Educational content generation pipeline using Ollama (qwen2.5:3b) to create structured lessons, subtopics, content, quizzes, and question banks.

## Features

- **CLI Input**: Interactive prompt for topic, lessons, subtopics, quality, length, quiz settings
- **Structured Planning**: Analyzes prompt → generates lessons → generates subtopics with character estimates
- **Content Generation**: Creates detailed content for each subtopic individually
- **Assessment Creation**: Generates quiz questions (multiple choice) and question banks per lesson
- **Organized Output**: Folder structure by prompt → lesson → subtopic with .txt and .csv files
- **Scalable Architecture**: Modular design with separate files for each pipeline stage

## Project Structure

```
content-generator/
├── core/
│   ├── llm/
│   │   ├── base.py          # Abstract LLM provider base class
│   │   ├── factory.py       # LLM provider factory
│   │   └── providers/
│   │       └── ollama.py    # Ollama implementation
│   ├── models/
│   │   └── schemas.py       # Pydantic data models
│   ├── planning/
│   │   ├── prompt_analyzer.py
│   │   ├── lesson_generator.py
│   │   └── subtopic_generator.py
│   ├── generation/
│   │   └── content_generator.py
│   ├── output/
│   │   └── writer.py        # File output handling
│   └── pipeline/
│       └── orchestrator.py  # Main pipeline coordinator
├── userinput.py             # CLI input handler
├── main.py                  # Entry point
├── requirements.txt
├── .env.example
└── README.md
```

## Prerequisites

1. **Ollama** installed and running
   ```bash
   # Install Ollama from https://ollama.ai
   ollama serve
   ```

2. **Pull the model**
   ```bash
   ollama pull qwen2.5:3b
   ```

3. **Python dependencies**
   ```bash
   pip install -r requirements.txt
   ```

## Usage

### Interactive Mode
```bash
python main.py
```

### With Configuration File
```bash
python main.py --input output/my_topic/user_input.json
```

### Custom Options
```bash
python main.py --model qwen2.5:3b --url http://localhost:11434 --output ./my_output
```

## CLI Input Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| Prompt | Main topic for content generation | Required |
| Lessons | Number of lessons (1-50) | 5 |
| Subtopics/Lesson | Subtopics per lesson (1-20) | 4 |
| Content Quality | technical / intermediate / beginner | intermediate |
| Content Length | extreme / long / medium / simple | medium |
| Quiz Questions | Questions per lesson (1-50) | 5 |
| Quiz Difficulty | technical / intermediate / beginner | intermediate |
| Question Bank | Questions per lesson (1-100) | 10 |

## Output Structure

```
output/
└── your_prompt_topic/
    ├── user_input.json           # Original configuration
    ├── generation_summary.json   # Overall statistics
    ├── lesson_1_title/
    │   ├── lesson_summary.json
    │   ├── quiz.csv              # Multiple choice questions
    │   ├── question_bank.csv     # Practice questions
    │   ├── subtopic_1/
    │   │   └── content.txt       # Generated content
    │   ├── subtopic_2/
    │   │   └── content.txt
    │   └── ...
    ├── lesson_2_title/
    │   └── ...
    └── ...
```

## Content Quality Levels

- **Beginner**: Simple explanations, analogies, minimal jargon
- **Intermediate**: Balanced technical depth with practical examples
- **Technical**: Deep technical details, code examples, formulas

## Content Length Levels

- **Simple**: ~500-1000 characters per subtopic
- **Medium**: ~1000-2000 characters per subtopic
- **Long**: ~2000-3000 characters per subtopic
- **Extreme**: 3000+ characters per subtopic

## Architecture

Each pipeline stage is in a separate file for scalability:

1. **PromptAnalyzer** - Analyzes topic for domain, complexity, prerequisites
2. **LessonGenerator** - Creates progressive lesson structure
3. **SubtopicGenerator** - Breaks lessons into detailed subtopics with char estimates
4. **ContentGenerator** - Generates content, quizzes, question banks per subtopic/lesson
5. **OutputWriter** - Writes organized file structure
6. **PipelineOrchestrator** - Coordinates all stages

## Extending

Add new LLM providers by implementing `BaseLLMProvider` and registering in `LLMFactory`.

```python
from core.llm.base import BaseLLMProvider
from core.llm.factory import LLMFactory

class MyProvider(BaseLLMProvider):
    # Implement required methods
    pass

LLMFactory.register_provider("myprovider", MyProvider)
```