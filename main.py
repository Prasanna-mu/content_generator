import sys
import argparse
import os
from pathlib import Path
from dotenv import load_dotenv

from core.pipeline.orchestrator import PipelineOrchestrator
from userinput import get_user_input, load_user_input_json


load_dotenv()


def main():
    parser = argparse.ArgumentParser(description="Content Generator - Sprint 1")
    parser.add_argument("--input", "-i", type=str, help="Path to user_input.json file")
    parser.add_argument("--model", "-m", type=str, default="qwen2.5:3b", help="Ollama model name")
    parser.add_argument("--url", "-u", type=str, default="http://localhost:11434", help="Ollama base URL")
    parser.add_argument("--output", "-o", type=str, default="output", help="Output directory")
    parser.add_argument("--provider", "-p", type=str, default="ollama", help="LLM provider")
    parser.add_argument("--workers", "-w", type=int, default=int(os.getenv("WORKER_COUNT", "4")), help="Number of parallel workers")
    
    args = parser.parse_args()
    
    try:
        orchestrator = PipelineOrchestrator(
            model_name=args.model,
            provider=args.provider,
            base_url=args.url,
            output_dir=Path(args.output),
            worker_count=args.workers
        )
        
        print("Initializing pipeline...")
        orchestrator.initialize()
        
        if args.input:
            json_path = Path(args.input)
            if not json_path.exists():
                print(f"Error: File not found: {json_path}")
                sys.exit(1)
            print(f"Loading configuration from: {json_path}")
            orchestrator.run_from_json(json_path)
        else:
            user_input = get_user_input()
            orchestrator.run(user_input)
            
    except ConnectionError as e:
        print(f"\nConnection Error: {e}")
        print("Make sure Ollama is running: ollama serve")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\nCancelled by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()