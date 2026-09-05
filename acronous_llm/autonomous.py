"""Autonomous learning entry point for the Acronous shared brain.

Run as a long-lived background service so the brain keeps learning from the
internet even when no user is interacting with EquiVO, Navigwiz, or Acronous
AI:

    python -m acronous_llm.autonomous [--interval 300]

Three learning phases run on different schedules:
  Phase 1 — Quick Scan (every 5 min): rotating topics, RSS feeds, search snippets
  Phase 2 — Deep Dive (every 30 min): full article extraction, concept mapping
  Phase 3 — Self-Evaluation (every 2 hours): gap detection, stale pruning

Combines both learning paths:
  * continuous internet knowledge growth (InternetLearner background thread)
  * post-interaction learning happens automatically whenever any product
    calls the brain (see AcronousAgentEngine.process / process_stream).

Usage as a library:
    from acronous_llm import start_autonomous_learning
    eng = start_autonomous_learning(interval_seconds=300)  # blocks
"""
import sys
import time
import logging
import argparse


def build_auto_engine():
    """Construct a fully-wired brain (neural + core + agent engine)."""
    sys.path.insert(0, ".")  # allow running from anywhere in the workspace
    from acronous_llm.neural import AcronousNeuralEngine
    from acronous_llm.core import AcronousCoreEngine
    from acronous_llm.agents import AcronousAgentEngine
    from acronous_llm.config import AcronousConfig
    config = AcronousConfig()
    neural = AcronousNeuralEngine(config)
    core = AcronousCoreEngine(config)
    agent = AcronousAgentEngine(neural, core)
    return agent


def start_autonomous_learning(interval_seconds=300, run_on_start=True):
    """Start continuous autonomous learning and block forever.

    - interval_seconds: seconds between quick-scan cycles (default 300 = 5 min)
    - run_on_start: immediately do one online sweep before entering the
      periodic schedule.
    Returns the agent engine (for programmatic use)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    agent = build_auto_engine()
    log = logging.getLogger("acronous.autonomous")

    if run_on_start:
        try:
            learned = agent.learn_from_internet_once()
            log.info("initial quick scan stored %s facts", learned)
        except Exception as exc:
            log.warning("initial scan failed: %s", exc)

        # Also do an initial deep dive
        try:
            learner = getattr(agent.core, "internet_learner", None)
            if learner:
                deep = learner.run_deep_dive(num_topics=3)
                log.info("initial deep dive stored %s facts", deep)
        except Exception as exc:
            log.warning("initial deep dive failed: %s", exc)

    learner = agent.start_internet_learning(interval_seconds=int(interval_seconds))
    if learner is None:
        log.error("could not start internet learner — check network/core wiring")
    else:
        log.info("autonomous internet learning running every %ss (3-phase cycle)", interval_seconds)
        log.info("  Phase 1: Quick scan every %ss", interval_seconds)
        log.info("  Phase 2: Deep dive every %ss", interval_seconds * 6)
        log.info("  Phase 3: Self-evaluation every %ss", interval_seconds * 24)

    log.info("Acronous shared brain is now continuously learning (Ctrl+C to stop).")
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        log.info("stopping autonomous learning")
        if learner is not None:
            learner.stop()
    return agent


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Acronous autonomous learner")
    parser.add_argument("--interval", type=int, default=300,
                        help="seconds between quick-scan cycles (default 300)")
    args = parser.parse_args()
    start_autonomous_learning(interval_seconds=args.interval)
