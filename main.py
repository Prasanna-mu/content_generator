import sys
import argparse
import os
from pathlib import Path
from dotenv import load_dotenv

from core.pipeline.orchestrator import PipelineOrchestrator
from userinput import get_user_input, load_user_input_json


load_dotenv()


def main():
    parser = argparse.ArgumentParser(description="Content Generator - Sprint 2: Persistent Session Management")
    parser.add_argument("--input", "-i", type=str, help="Path to user_input.json file")
    parser.add_argument("--model", "-m", type=str, default="qwen2.5:3b", help="Ollama model name")
    parser.add_argument("--url", "-u", type=str, default="http://localhost:11434", help="Ollama base URL")
    parser.add_argument("--output", "-o", type=str, default="output", help="Output directory")
    parser.add_argument("--provider", "-p", type=str, default="ollama", help="LLM provider")
    parser.add_argument("--workers", "-w", type=int, default=int(os.getenv("WORKER_COUNT", "4")), help="Number of parallel workers")
    
    # Session management arguments
    parser.add_argument("--session-id", "-s", type=str, help="Session ID to resume or use")
    parser.add_argument("--resume", "-r", action="store_true", help="Resume the specified session")
    parser.add_argument("--list-sessions", "-l", action="store_true", help="List all sessions and exit")
    parser.add_argument("--session-info", type=str, help="Show info for a specific session and exit")
    parser.add_argument("--processing-dir", type=str, default="processing", help="Processing directory for sessions and checkpoints")
    
    args = parser.parse_args()
    
    try:
        orchestrator = PipelineOrchestrator(
            model_name=args.model,
            provider=args.provider,
            base_url=args.url,
            output_dir=Path(args.output),
            worker_count=args.workers,
            processing_dir=Path(args.processing_dir),
            session_id=args.session_id,
            resume=args.resume
        )
        
        if args.list_sessions or args.session_info:
            orchestrator.initialize_session_manager()
        else:
            print("Initializing pipeline...")
            orchestrator.initialize()
        
        if args.list_sessions:
            sessions = orchestrator.list_sessions()
            if not sessions:
                print("No sessions found.")
            else:
                print(f"\n{'Session ID':<38} {'Status':<12} {'Prompt':<40} {'Lessons':<8} {'Created'}")
                print("-" * 120)
                for s in sessions:
                    prompt_short = s.prompt[:37] + "..." if len(s.prompt) > 40 else s.prompt
                    print(f"{s.session_id:<38} {s.status.value:<12} {prompt_short:<40} {s.total_lessons:<8} {s.created_at.strftime('%Y-%m-%d %H:%M')}")
            return
        
        if args.session_info:
            session = orchestrator.get_session_info(args.session_info)
            if not session:
                print(f"Session {args.session_info} not found.")
                sys.exit(1)
            print(f"\nSession: {session.session_id}")
            print(f"  Status: {session.status.value}")
            print(f"  Prompt: {session.prompt}")
            print(f"  Created: {session.created_at}")
            print(f"  Updated: {session.updated_at}")
            print(f"  Total Lessons: {session.total_lessons}")
            print(f"  Completed Lessons: {session.completed_lessons}")
            if session.error_message:
                print(f"  Error: {session.error_message}")
            print(f"  Config: {session.config}")
            return
        
        if args.resume and not args.session_id:
            print("Error: --resume requires --session-id")
            sys.exit(1)
        
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
    finally:
        try:
            orchestrator.close()
        except:
            pass


if __name__ == "__main__":
    main()