#!/usr/bin/env python3
"""
Apex AI — Local Autonomous Intelligence Engine
Run: streamlit run run.py
"""

import os
import sys
import subprocess
import argparse

def main():
    parser = argparse.ArgumentParser(
        description="Apex AI — Local Autonomous Neural Agent"
    )
    parser.add_argument(
        "--mode", choices=["ui", "cli", "train"], default="ui",
        help="Run mode: ui (Streamlit), cli (terminal), train (train models)"
    )
    parser.add_argument("--query", "-q", help="Query for CLI mode")
    parser.add_argument("--port", "-p", type=int, default=8501, help="Streamlit port")
    parser.add_argument(
        "--model", help="Model name override"
    )
    parser.add_argument("--install", action="store_true", help="Install dependencies")

    args = parser.parse_args()

    if args.install:
        install_deps()
        return

    if args.model:
        os.environ["APEX_LLM_MODEL"] = args.model

    if args.mode == "ui":
        run_ui(args.port)
    elif args.mode == "cli":
        run_cli(args.query)
    elif args.mode == "train":
        run_train()

def install_deps():
    print("[APEX] Installing Apex AI dependencies...")
    deps = [
        "streamlit>=1.28.0",
        "torch>=2.0.0",
        "transformers>=4.30.0",
        "duckduckgo_search>=4.0.0",
        "pillow>=10.0.0",
        "beautifulsoup4>=4.12.0",
        "requests>=2.31.0",
        "numpy>=1.24.0",
    ]
    for dep in deps:
        print(f"  Installing {dep}...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", dep, "-q"]
        )
    print("\nOptional extras:")
    print("  pip install sentence-transformers  (better embeddings)")
    print("  pip install openai-whisper          (speech-to-text)")
    print("  pip install easyocr                 (OCR in images)")
    print("  pip install sounddevice              (microphone input)")
    print("  pip install edge-tts                 (text-to-speech)")
    print("\nFor local LLM (recommended):")
    print("  1. Install Ollama from https://ollama.ai")
    print("  2. Run: ollama pull llama3.2:1b")
    print("\n✅ Apex AI ready!")

def run_ui(port):
    script_path = os.path.join(os.path.dirname(__file__), "frontend", "app.py")
    print(f"\n[APEX] Starting on port {port}...")
    print(f"   Open: http://localhost:{port}\n")
    subprocess.run([
        sys.executable, "-m", "streamlit", "run", script_path,
        "--server.port", str(port),
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false"
    ])

def run_cli(query=None):
    sys.path.insert(0, os.path.dirname(__file__))
    from apex_llm import ApexConfig, ApexNeuralEngine, ApexCoreEngine, ApexAgentEngine

    config = ApexConfig()
    config.load_env_file()
    config.save()
    neural = ApexNeuralEngine(config)
    core = ApexCoreEngine(config)
    agent = ApexAgentEngine(neural, core)

    print("[APEX] Apex AI - Local Neural Agent")
    print("Type 'exit' to quit, '/help' for commands\n")

    if query:
        result = agent.process(query)
        print(f"\nApex AI: {result['content']}\n")
        return

    while True:
        try:
            user_input = input("You: ").strip()
            if user_input.lower() in ("exit", "quit"):
                break
            if user_input.lower() == "/help":
                print("Commands: /clear, /stats, /search <query>, /exit")
                continue
            if not user_input:
                continue
            result = agent.process(user_input, "cli_session")
            print(f"\nApex AI ({result.get('type', 'chat')}): {result['content']}\n")
        except KeyboardInterrupt:
            print("\n\nGoodbye!")
            break

def run_train():
    print("[APEX] Training Apex Neural Network...")
    sys.path.insert(0, os.path.dirname(__file__))
    from apex_llm import ApexConfig, ApexNeuralEngine

    config = ApexConfig()
    neural = ApexNeuralEngine(config)

    import torch
    sample_data = torch.randn(100, config.EMBED_DIM)
    neural.cluster_queries(sample_data)

    neural.save_state(str(config.CLASSIFIER_PATH))
    print(f"✅ Models saved to {config.MODELS_DIR}")

if __name__ == "__main__":
    main()
